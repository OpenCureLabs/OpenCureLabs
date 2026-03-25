/**
 * OpenCure Labs — Ingest Worker
 *
 * POST /results       — accepts a signed result payload, verifies Ed25519 signature,
 *                       writes the full object to R2, indexes a row in D1 as 'pending'.
 *
 * GET  /results       — queries D1 with optional filters. Default: published results only.
 *                       ?status=pending available for batch sweep.
 *
 * PATCH /results/:id  — admin-only: update result status (published/blocked) after review.
 *
 * POST /contributors  — register a contributor's Ed25519 public key.
 *
 * GET  /contributors  — admin-only: list registered contributors.
 *
 * POST /critiques     — attach a critique to a result.
 * GET  /critiques     — query critiques.
 *
 * GET  /tasks/claim   — claim available research tasks from central queue.
 * POST /tasks/:id/complete — mark a claimed task as completed.
 * GET  /tasks/stats   — task queue statistics.
 * POST /tasks/generate — admin-only: populate task queue from parameter banks.
 *
 * Storage:
 *   R2  → results/{skill}/{YYYY-MM-DD}/{uuid}.json   (immutable blobs)
 *   R2  → latest.json                                (rolling feed, 100 published entries)
 *   D1  → results table                              (queryable index)
 *   D1  → contributors table                         (public key registry)
 *   D1  → tasks table                                (central research task queue)
 */

import { generateAllTasks, inputHash, type TaskInput } from "./tasks";

const KNOWN_SKILLS = [
    "neoantigen_prediction",
    "structure_prediction",
    "molecular_docking",
    "qsar",
    "variant_pathogenicity",
    "sequencing_qc",
    "grok_research",
    "report_generator",
] as const;

const PUBLIC_BASE_URL = "https://pub.opencurelabs.ai";

const CORS_HEADERS: Record<string, string> = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Contributor-Key, X-Signature, X-Admin-Key",
};

interface Env {
    RESULTS_BUCKET: R2Bucket;
    RESULTS_DB: D1Database;
    ADMIN_KEY?: string;
}

interface IngestPayload {
    skill: string;
    result_data: unknown;
    novel?: boolean;
    status?: string;
    contributor_id?: string;
    species?: string;
    local_critique?: unknown;
    summary?: {
        confidence_score?: number;
        gene?: string;
    };
}

interface LatestEntry {
    id: string;
    skill: string;
    date: string;
    novel: boolean;
    status: string;
    url: string;
    species: string;
    confidence_score: number | null;
    gene: string | null;
    created_at: string;
}

export default {
    async fetch(request: Request, env: Env): Promise<Response> {
        if (request.method === "OPTIONS") {
            return new Response(null, { headers: CORS_HEADERS });
        }

        const url = new URL(request.url);

        if (request.method === "POST" && url.pathname === "/results") {
            return handlePost(request, env);
        }

        if (request.method === "GET" && url.pathname === "/results/count") {
            return handleGetCount(request, env);
        }

        if (request.method === "GET" && url.pathname === "/results") {
            return handleGet(request, env);
        }

        if (request.method === "PATCH" && url.pathname.startsWith("/results/")) {
            return handlePatchResult(request, env);
        }

        if (request.method === "POST" && url.pathname === "/contributors") {
            return handlePostContributor(request, env);
        }

        if (request.method === "GET" && url.pathname === "/contributors") {
            return handleGetContributors(request, env);
        }

        if (request.method === "POST" && url.pathname === "/critiques") {
            return handlePostCritique(request, env);
        }

        if (request.method === "GET" && url.pathname === "/critiques") {
            return handleGetCritiques(request, env);
        }

        // ── Task Queue Routes ───────────────────────────────────────────
        if (request.method === "GET" && url.pathname === "/tasks/claim") {
            return handleTaskClaim(request, env);
        }

        if (request.method === "POST" && url.pathname.match(/^\/tasks\/[^/]+\/complete$/)) {
            return handleTaskComplete(request, env);
        }

        if (request.method === "GET" && url.pathname === "/tasks/stats") {
            return handleTaskStats(env);
        }

        if (request.method === "POST" && url.pathname === "/tasks/generate") {
            return handleTaskGenerate(request, env);
        }

        return json({ error: "Not found" }, 404);
    },

    async scheduled(_event: ScheduledEvent, env: Env, _ctx: ExecutionContext): Promise<void> {
        // Weekly cron: populate task queue + reclaim expired tasks
        await populateTaskQueue(env);
        await reclaimExpiredTasks(env);
    },
};

// ── Signature Verification ────────────────────────────────────────────────────

function hexToBytes(hex: string): Uint8Array {
    const bytes = new Uint8Array(hex.length / 2);
    for (let i = 0; i < hex.length; i += 2) {
        bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
    }
    return bytes;
}

/**
 * Verify an Ed25519 signature against raw body bytes.
 *
 * The Python client signs json.dumps(payload, sort_keys=True, separators=(",",":"))
 * and sends exactly those bytes as the request body.  We verify against
 * the raw body to avoid any parse/re-serialize mismatch (e.g. 42.0 vs 42).
 */
async function verifySignatureRaw(
    publicKeyHex: string,
    signatureB64: string,
    rawBody: string
): Promise<boolean> {
    try {
        const keyBytes = hexToBytes(publicKeyHex);
        const key = await crypto.subtle.importKey(
            "raw",
            keyBytes,
            { name: "Ed25519" },
            false,
            ["verify"]
        );

        const signatureBytes = Uint8Array.from(atob(signatureB64), (c) => c.charCodeAt(0));
        const payloadBytes = new TextEncoder().encode(rawBody);

        return await crypto.subtle.verify("Ed25519", key, signatureBytes, payloadBytes);
    } catch {
        return false;
    }
}

// ── POST /results ─────────────────────────────────────────────────────────────

async function handlePost(request: Request, env: Env): Promise<Response> {
    // Require signature headers
    const contributorKey = request.headers.get("X-Contributor-Key");
    const signature = request.headers.get("X-Signature");

    if (!contributorKey || !signature) {
        return json({ error: "Signature required. Set X-Contributor-Key and X-Signature headers." }, 401);
    }

    // Look up contributor
    const contributor = await env.RESULTS_DB.prepare(
        "SELECT contributor_id, status FROM contributors WHERE public_key = ?"
    )
        .bind(contributorKey)
        .first<{ contributor_id: string; status: string }>();

    if (!contributor) {
        return json({ error: "Unknown contributor — POST to /contributors first" }, 401);
    }

    if (contributor.status === "banned") {
        return json({ error: "Contributor suspended" }, 403);
    }

    // Read raw body BEFORE parsing — signature must be verified against the exact
    // bytes the client signed, not a re-serialised version (JS and Python differ
    // on float formatting e.g. 42.0 vs 42).
    let rawBody: string;
    let payload: IngestPayload;

    try {
        rawBody = await request.text();
        payload = JSON.parse(rawBody) as IngestPayload;
    } catch {
        return json({ error: "Invalid JSON body" }, 400);
    }

    // Verify Ed25519 signature against the raw bytes
    const valid = await verifySignatureRaw(contributorKey, signature, rawBody);
    if (!valid) {
        return json({ error: "Invalid signature" }, 403);
    }

    // Validate required fields
    if (!payload.skill || payload.result_data === undefined || payload.result_data === null) {
        return json({ error: "Missing required fields: skill, result_data" }, 400);
    }

    // Validate skill enum
    if (!(KNOWN_SKILLS as readonly string[]).includes(payload.skill)) {
        return json({ error: `Unknown skill '${payload.skill}'. Valid skills: ${KNOWN_SKILLS.join(", ")}` }, 400);
    }

    // ── Dedup: check if a matching task was already completed ────────────
    const resultData0 = payload.result_data as Record<string, unknown>;
    const dedupInput: Record<string, unknown> = {};
    // Build a canonical input from the result data for dedup matching
    for (const k of ["sample_id", "vcf_path", "hla_alleles", "tumor_type", "species",
        "protein_id", "sequence", "method", "variant_id", "gene", "hgvs",
        "dataset_path", "target_column", "model_type", "mode",
        "ligand_smiles", "receptor_pdb"]) {
        if (resultData0[k] !== undefined) dedupInput[k] = resultData0[k];
    }
    if (Object.keys(dedupInput).length > 0) {
        const hash = await inputHash(dedupInput);
        const existing = await env.RESULTS_DB.prepare(
            `SELECT id FROM tasks WHERE input_hash = ? AND status = 'completed'`
        ).bind(hash).first();
        if (existing) {
            return json({ error: "Duplicate result — task already completed", task_id: existing.id }, 409);
        }
    }

    // local_critique is optional — results without it go to pending for sweep review

    const id = crypto.randomUUID();
    const now = new Date();
    const date = now.toISOString().split("T")[0];
    const createdAt = now.toISOString();
    // All results start as pending — batch sweep publishes after verification
    const status = "pending";
    const novel = payload.novel === true;

    const key = `results/${payload.skill}/${date}/${id}.json`;
    const r2Url = `${PUBLIC_BASE_URL}/${key}`;

    // Extract lightweight summary fields from result_data
    const resultData = payload.result_data as Record<string, unknown>;
    const confidenceScore =
        typeof resultData?.confidence_score === "number" ? resultData.confidence_score : null;
    const gene = typeof resultData?.gene === "string" ? resultData.gene : null;
    const species =
        typeof payload.species === "string" && payload.species
            ? payload.species
            : typeof resultData?.species === "string" && resultData.species
                ? (resultData.species as string)
                : "human";

    // Write full result object to R2 (includes local_critique if provided)
    const resultObject = {
        id,
        skill: payload.skill,
        date,
        novel,
        status,
        species,
        result_data: payload.result_data,
        ...(payload.local_critique ? { local_critique: payload.local_critique } : {}),
        created_at: createdAt,
    };

    await env.RESULTS_BUCKET.put(key, JSON.stringify(resultObject, null, 2), {
        httpMetadata: { contentType: "application/json" },
    });

    // Insert index row into D1
    await env.RESULTS_DB.prepare(
        `INSERT INTO results
       (id, skill, date, novel, status, r2_url, species, confidence_score, gene, contributor_id, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
        .bind(
            id,
            payload.skill,
            date,
            novel ? 1 : 0,
            status,
            r2Url,
            species,
            confidenceScore,
            gene,
            contributor.contributor_id,
            createdAt
        )
        .run();

    // Auto-complete matching task if one exists
    if (Object.keys(dedupInput).length > 0) {
        const hash = await inputHash(dedupInput);
        await env.RESULTS_DB.prepare(
            `UPDATE tasks SET status = 'completed', completed_at = ?, result_id = ?
             WHERE input_hash = ? AND status IN ('available', 'claimed')`
        ).bind(createdAt, id, hash).run();
    }

    return json({ id, url: r2Url, status: "pending" }, 201);
}

// ── GET /results/count ────────────────────────────────────────────────────────

async function handleGetCount(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const skill = url.searchParams.get("skill");
    const novelParam = url.searchParams.get("novel");
    const speciesParam = url.searchParams.get("species");

    // Total published
    const totalRow = await env.RESULTS_DB.prepare(
        "SELECT COUNT(*) as cnt FROM results WHERE status = 'published'"
    ).first<{ cnt: number }>();

    // Novel published
    const novelRow = await env.RESULTS_DB.prepare(
        "SELECT COUNT(*) as cnt FROM results WHERE status = 'published' AND novel = 1"
    ).first<{ cnt: number }>();

    // Today
    const today = new Date().toISOString().split("T")[0];
    const todayRow = await env.RESULTS_DB.prepare(
        "SELECT COUNT(*) as cnt FROM results WHERE status = 'published' AND date = ?"
    ).bind(today).first<{ cnt: number }>();

    // Distinct skills
    const skillsRow = await env.RESULTS_DB.prepare(
        "SELECT COUNT(DISTINCT skill) as cnt FROM results WHERE status = 'published'"
    ).first<{ cnt: number }>();

    return json({
        total: totalRow?.cnt ?? 0,
        novel: novelRow?.cnt ?? 0,
        today: todayRow?.cnt ?? 0,
        skills: skillsRow?.cnt ?? 0,
    });
}

// ── GET /results ──────────────────────────────────────────────────────────────

async function handleGet(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const skill = url.searchParams.get("skill");
    const date = url.searchParams.get("date");
    const novelParam = url.searchParams.get("novel");
    const statusParam = url.searchParams.get("status");
    const afterParam = url.searchParams.get("after");
    const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "50", 10), 200);

    let query =
        "SELECT id, skill, date, novel, status, r2_url, species, confidence_score, gene, created_at FROM results WHERE 1=1";
    const bindings: (string | number)[] = [];

    // Default to published results only (public-facing)
    if (statusParam) {
        query += " AND status = ?";
        bindings.push(statusParam);
    } else {
        query += " AND status = ?";
        bindings.push("published");
    }

    if (skill) {
        query += " AND skill = ?";
        bindings.push(skill);
    }
    if (date) {
        query += " AND date = ?";
        bindings.push(date);
    }
    if (novelParam !== null) {
        query += " AND novel = ?";
        bindings.push(novelParam === "true" ? 1 : 0);
    }
    const speciesParam = url.searchParams.get("species");
    if (speciesParam) {
        query += " AND species = ?";
        bindings.push(speciesParam);
    }
    if (afterParam) {
        query += " AND created_at < ?";
        bindings.push(afterParam);
    }

    // Fetch one extra to detect has_more
    query += " ORDER BY created_at DESC LIMIT ?";
    bindings.push(limit + 1);

    const result = await env.RESULTS_DB.prepare(query)
        .bind(...bindings)
        .all();

    const rows = result.results;
    const hasMore = rows.length > limit;
    const page = hasMore ? rows.slice(0, limit) : rows;
    const nextCursor = hasMore && page.length > 0
        ? (page[page.length - 1] as Record<string, unknown>).created_at as string
        : null;

    return json({
        results: page,
        count: page.length,
        has_more: hasMore,
        next_cursor: nextCursor,
    });
}

// ── PATCH /results/:id ────────────────────────────────────────────────────────

async function handlePatchResult(request: Request, env: Env): Promise<Response> {
    // Admin-only endpoint
    const adminKey = request.headers.get("X-Admin-Key");
    if (!env.ADMIN_KEY || adminKey !== env.ADMIN_KEY) {
        return json({ error: "Unauthorized" }, 401);
    }

    const url = new URL(request.url);
    const id = url.pathname.split("/results/")[1];
    if (!id) {
        return json({ error: "Missing result ID" }, 400);
    }

    let body: { status: string; batch_critique?: unknown };
    try {
        body = (await request.json()) as { status: string; batch_critique?: unknown };
    } catch {
        return json({ error: "Invalid JSON body" }, 400);
    }

    if (!body.status || !["published", "blocked"].includes(body.status)) {
        return json({ error: "status must be 'published' or 'blocked'" }, 400);
    }

    // Update D1
    const now = new Date().toISOString();
    await env.RESULTS_DB.prepare(
        "UPDATE results SET status = ?, reviewed_at = ? WHERE id = ?"
    )
        .bind(body.status, now, id)
        .run();

    // If batch_critique provided, append to R2 object and index in critiques table
    if (body.batch_critique) {
        const row = await env.RESULTS_DB.prepare("SELECT r2_url, skill, date FROM results WHERE id = ?")
            .bind(id)
            .first<{ r2_url: string; skill: string; date: string }>();

        if (row) {
            const key = `results/${row.skill}/${row.date}/${id}.json`;
            const existing = await env.RESULTS_BUCKET.get(key);
            if (existing) {
                const obj = JSON.parse(await existing.text());
                obj.status = body.status;
                obj.batch_critique = body.batch_critique;
                obj.reviewed_at = now;
                await env.RESULTS_BUCKET.put(key, JSON.stringify(obj, null, 2), {
                    httpMetadata: { contentType: "application/json" },
                });
            }

            // Also insert into critiques table so the frontend sees the review
            const bc = body.batch_critique as Record<string, unknown>;
            const critiqueId = crypto.randomUUID();
            const critiqueKey = `critiques/${row.skill}/${row.date}/grok_sweep/${critiqueId}.json`;
            const critiqueUrl = `${PUBLIC_BASE_URL}/${critiqueKey}`;

            const critiqueObject = {
                id: critiqueId,
                result_id: id,
                reviewer: "grok_sweep",
                overall_score: bc.verification_score ?? null,
                recommendation: bc.recommendation ?? null,
                critique_data: bc,
                created_at: now,
            };

            await env.RESULTS_BUCKET.put(critiqueKey, JSON.stringify(critiqueObject, null, 2), {
                httpMetadata: { contentType: "application/json" },
            });

            await env.RESULTS_DB.prepare(
                `INSERT INTO critiques (id, result_id, reviewer, overall_score, recommendation, critique_data, r2_url, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
            )
                .bind(
                    critiqueId,
                    id,
                    "grok_sweep",
                    (bc.verification_score as number) ?? null,
                    (bc.recommendation as string) ?? null,
                    JSON.stringify(bc),
                    critiqueUrl,
                    now
                )
                .run();
        }
    }

    // If published, update latest.json feed
    if (body.status === "published") {
        const row = await env.RESULTS_DB.prepare(
            "SELECT id, skill, date, novel, status, r2_url, species, confidence_score, gene, created_at FROM results WHERE id = ?"
        )
            .bind(id)
            .first<LatestEntry & { r2_url: string }>();

        if (row) {
            await updateLatest(env, {
                id: row.id,
                skill: row.skill,
                date: row.date,
                novel: !!row.novel,
                status: "published",
                url: row.r2_url,
                species: row.species,
                confidence_score: row.confidence_score,
                gene: row.gene,
                created_at: row.created_at,
            });
        }
    }

    return json({ id, status: body.status, reviewed_at: now });
}

// ── POST /contributors ────────────────────────────────────────────────────────

async function handlePostContributor(request: Request, env: Env): Promise<Response> {
    let body: { contributor_id: string; public_key: string };
    try {
        body = (await request.json()) as { contributor_id: string; public_key: string };
    } catch {
        return json({ error: "Invalid JSON body" }, 400);
    }

    if (!body.contributor_id || !body.public_key) {
        return json({ error: "Missing required fields: contributor_id, public_key" }, 400);
    }

    // Validate public_key is 64 hex chars (32 bytes)
    if (!/^[0-9a-f]{64}$/i.test(body.public_key)) {
        return json({ error: "public_key must be a 64-character hex string (32-byte Ed25519 key)" }, 400);
    }

    const now = new Date().toISOString();

    try {
        await env.RESULTS_DB.prepare(
            `INSERT INTO contributors (contributor_id, public_key, status, created_at)
             VALUES (?, ?, 'active', ?)`
        )
            .bind(body.contributor_id, body.public_key.toLowerCase(), now)
            .run();
    } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("UNIQUE") || msg.includes("constraint")) {
            return json({ error: "Contributor or key already registered" }, 409);
        }
        throw e;
    }

    return json({ contributor_id: body.contributor_id, status: "active" }, 201);
}

// ── GET /contributors ─────────────────────────────────────────────────────────

async function handleGetContributors(request: Request, env: Env): Promise<Response> {
    const adminKey = request.headers.get("X-Admin-Key");
    if (!env.ADMIN_KEY || adminKey !== env.ADMIN_KEY) {
        return json({ error: "Unauthorized" }, 401);
    }

    const rows = await env.RESULTS_DB.prepare(
        `SELECT c.contributor_id, c.public_key, c.status, c.created_at,
                COUNT(r.id) as result_count
         FROM contributors c
         LEFT JOIN results r ON r.contributor_id = c.contributor_id
         GROUP BY c.contributor_id
         ORDER BY c.created_at DESC`
    ).all();

    return json({ contributors: rows.results, count: rows.results.length });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

interface CritiquePayload {
    result_id: string;
    reviewer: string;
    overall_score?: number;
    recommendation?: string;
    critique_data: unknown;
}

// ── POST /critiques ───────────────────────────────────────────────────────────

async function handlePostCritique(request: Request, env: Env): Promise<Response> {
    let payload: CritiquePayload;

    try {
        payload = (await request.json()) as CritiquePayload;
    } catch {
        return json({ error: "Invalid JSON body" }, 400);
    }

    if (!payload.result_id || !payload.reviewer || payload.critique_data === undefined) {
        return json({ error: "Missing required fields: result_id, reviewer, critique_data" }, 400);
    }

    // Verify result exists
    const result = await env.RESULTS_DB.prepare("SELECT id, skill, date FROM results WHERE id = ?")
        .bind(payload.result_id)
        .first();

    if (!result) {
        return json({ error: `Result '${payload.result_id}' not found` }, 404);
    }

    const id = crypto.randomUUID();
    const now = new Date();
    const createdAt = now.toISOString();

    // Write full critique to R2
    const key = `critiques/${result.skill}/${result.date}/${payload.reviewer}/${id}.json`;
    const r2Url = `${PUBLIC_BASE_URL}/${key}`;

    const critiqueObject = {
        id,
        result_id: payload.result_id,
        reviewer: payload.reviewer,
        overall_score: payload.overall_score ?? null,
        recommendation: payload.recommendation ?? null,
        critique_data: payload.critique_data,
        created_at: createdAt,
    };

    await env.RESULTS_BUCKET.put(key, JSON.stringify(critiqueObject, null, 2), {
        httpMetadata: { contentType: "application/json" },
    });

    // Index in D1
    await env.RESULTS_DB.prepare(
        `INSERT INTO critiques (id, result_id, reviewer, overall_score, recommendation, critique_data, r2_url, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    )
        .bind(
            id,
            payload.result_id,
            payload.reviewer,
            payload.overall_score ?? null,
            payload.recommendation ?? null,
            JSON.stringify(payload.critique_data),
            r2Url,
            createdAt
        )
        .run();

    // Mark result as reviewed
    await env.RESULTS_DB.prepare("UPDATE results SET reviewed_at = ? WHERE id = ?")
        .bind(createdAt, payload.result_id)
        .run();

    return json({ id, url: r2Url }, 201);
}

// ── GET /critiques ────────────────────────────────────────────────────────────

async function handleGetCritiques(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const resultId = url.searchParams.get("result_id");
    const reviewer = url.searchParams.get("reviewer");
    const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "50", 10), 200);

    let query =
        "SELECT id, result_id, reviewer, overall_score, recommendation, critique_data, r2_url, created_at FROM critiques WHERE 1=1";
    const bindings: (string | number)[] = [];

    if (resultId) {
        query += " AND result_id = ?";
        bindings.push(resultId);
    }
    if (reviewer) {
        query += " AND reviewer = ?";
        bindings.push(reviewer);
    }

    query += " ORDER BY created_at DESC LIMIT ?";
    bindings.push(limit);

    const result = await env.RESULTS_DB.prepare(query)
        .bind(...bindings)
        .all();

    return json({ critiques: result.results, count: result.results.length });
}

// ── Latest Feed + JSON Helper ─────────────────────────────────────────────────

async function updateLatest(env: Env, entry: LatestEntry): Promise<void> {
    let entries: LatestEntry[] = [];

    const existing = await env.RESULTS_BUCKET.get("latest.json");
    if (existing) {
        try {
            entries = JSON.parse(await existing.text()) as LatestEntry[];
        } catch {
            entries = [];
        }
    }

    entries.unshift(entry);
    if (entries.length > 100) {
        entries = entries.slice(0, 100);
    }

    await env.RESULTS_BUCKET.put("latest.json", JSON.stringify(entries, null, 2), {
        httpMetadata: { contentType: "application/json" },
    });
}

// ── Task Queue Handlers ─────────────────────────────────────────────────

/**
 * GET /tasks/claim?skill=neoantigen_prediction&count=5&contributor_id=abc
 * Atomically claim available tasks. Returns claimed tasks with input_data.
 */
async function handleTaskClaim(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const skill = url.searchParams.get("skill");
    const count = Math.min(parseInt(url.searchParams.get("count") ?? "5", 10), 50);
    const contributorId = url.searchParams.get("contributor_id") ?? "anonymous";

    if (count < 1) return json({ error: "count must be >= 1" }, 400);

    const now = new Date().toISOString();

    let query = `SELECT id, skill, input_data, domain, species, label, priority
                 FROM tasks WHERE status = 'available'`;
    const params: unknown[] = [];

    if (skill) {
        query += ` AND skill = ?`;
        params.push(skill);
    }
    query += ` ORDER BY priority ASC, created_at ASC LIMIT ?`;
    params.push(count);

    const available = await env.RESULTS_DB.prepare(query).bind(...params).all();

    if (!available.results?.length) {
        return json({ tasks: [], claimed: 0 });
    }

    // Atomically claim each task
    const claimed = [];
    for (const task of available.results) {
        const update = await env.RESULTS_DB.prepare(
            `UPDATE tasks SET status = 'claimed', claimed_by = ?, claimed_at = ?
             WHERE id = ? AND status = 'available'`
        ).bind(contributorId, now, task.id).run();

        if (update.meta.changes > 0) {
            claimed.push({
                id: task.id,
                skill: task.skill,
                input_data: typeof task.input_data === "string" ? JSON.parse(task.input_data as string) : task.input_data,
                domain: task.domain,
                species: task.species,
                label: task.label,
            });
        }
    }

    return json({ tasks: claimed, claimed: claimed.length });
}

/**
 * POST /tasks/:id/complete  { result_id: "..." }
 * Mark a claimed task as completed and link to the result.
 */
async function handleTaskComplete(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/tasks\/([^/]+)\/complete$/);
    if (!match) return json({ error: "Invalid path" }, 400);

    const taskId = match[1];
    const body = await request.json<{ result_id?: string }>();

    const now = new Date().toISOString();

    const result = await env.RESULTS_DB.prepare(
        `UPDATE tasks SET status = 'completed', completed_at = ?, result_id = ?
         WHERE id = ? AND status = 'claimed'`
    ).bind(now, body.result_id ?? null, taskId).run();

    if (result.meta.changes === 0) {
        return json({ error: "Task not found or not in claimed state" }, 404);
    }

    return json({ ok: true, task_id: taskId });
}

/**
 * GET /tasks/stats
 * Return aggregate counts by status, optionally filtered by skill or domain.
 */
async function handleTaskStats(env: Env): Promise<Response> {
    const stats = await env.RESULTS_DB.prepare(
        `SELECT status, skill, COUNT(*) as count FROM tasks GROUP BY status, skill ORDER BY status, skill`
    ).all();

    const totals = await env.RESULTS_DB.prepare(
        `SELECT status, COUNT(*) as count FROM tasks GROUP BY status`
    ).all();

    return json({ by_skill: stats.results, totals: totals.results });
}

/**
 * POST /tasks/generate  (admin-only)
 * Populate the task queue from parameter banks. Idempotent via input_hash UNIQUE.
 */
async function handleTaskGenerate(request: Request, env: Env): Promise<Response> {
    const adminKey = request.headers.get("X-Admin-Key");
    if (env.ADMIN_KEY && adminKey !== env.ADMIN_KEY) {
        return json({ error: "Unauthorized" }, 401);
    }

    const inserted = await populateTaskQueue(env);
    return json({ ok: true, inserted, message: `Generated ${inserted} new tasks` });
}

/**
 * Generate tasks and INSERT OR IGNORE into D1. Returns count of newly inserted tasks.
 */
async function populateTaskQueue(env: Env): Promise<number> {
    const allTasks = generateAllTasks();
    let inserted = 0;

    // Process in batches of 50 to avoid D1 limits
    const batchSize = 50;
    for (let i = 0; i < allTasks.length; i += batchSize) {
        const batch = allTasks.slice(i, i + batchSize);
        const stmts = [];

        for (const task of batch) {
            const hash = await inputHash(task.input_data);
            const id = crypto.randomUUID();
            stmts.push(
                env.RESULTS_DB.prepare(
                    `INSERT OR IGNORE INTO tasks (id, skill, input_hash, input_data, domain, species, label, priority)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
                ).bind(id, task.skill, hash, JSON.stringify(task.input_data), task.domain, task.species, task.label, task.priority)
            );
        }

        const results = await env.RESULTS_DB.batch(stmts);
        for (const r of results) {
            if (r.meta.changes > 0) inserted++;
        }
    }

    return inserted;
}

/**
 * Reclaim tasks that have been claimed for > 24 hours without completion.
 */
async function reclaimExpiredTasks(env: Env): Promise<number> {
    const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const result = await env.RESULTS_DB.prepare(
        `UPDATE tasks SET status = 'available', claimed_by = NULL, claimed_at = NULL
         WHERE status = 'claimed' AND claimed_at < ?`
    ).bind(cutoff).run();
    return result.meta.changes;
}

function json(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
        status,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
    });
}
