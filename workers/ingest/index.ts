/**
 * OpenCure Labs — Ingest Worker
 *
 * POST /results  — accepts a result payload from a user's CLI, validates it,
 *                  writes the full object to R2, indexes a row in D1, and
 *                  updates the rolling latest.json feed.
 *
 * GET  /results  — queries D1 with optional ?skill= &date= &novel= &limit= filters.
 *                  contributor_id is stripped from responses (admin-only field).
 *
 * Storage:
 *   R2  → results/{skill}/{YYYY-MM-DD}/{uuid}.json   (immutable blobs)
 *   R2  → latest.json                                (rolling feed, 100 entries)
 *   D1  → results table                              (queryable index)
 */

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
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
};

interface Env {
    RESULTS_BUCKET: R2Bucket;
    RESULTS_DB: D1Database;
}

interface IngestPayload {
    skill: string;
    result_data: unknown;
    novel?: boolean;
    status?: string;
    contributor_id?: string;
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

        if (request.method === "GET" && url.pathname === "/results") {
            return handleGet(request, env);
        }

        return json({ error: "Not found" }, 404);
    },
};

// ── POST /results ─────────────────────────────────────────────────────────────

async function handlePost(request: Request, env: Env): Promise<Response> {
    let payload: IngestPayload;

    try {
        payload = (await request.json()) as IngestPayload;
    } catch {
        return json({ error: "Invalid JSON body" }, 400);
    }

    // Validate required fields
    if (!payload.skill || payload.result_data === undefined || payload.result_data === null) {
        return json({ error: "Missing required fields: skill, result_data" }, 400);
    }

    // Validate skill enum
    if (!(KNOWN_SKILLS as readonly string[]).includes(payload.skill)) {
        return json({ error: `Unknown skill '${payload.skill}'. Valid skills: ${KNOWN_SKILLS.join(", ")}` }, 400);
    }

    const id = crypto.randomUUID();
    const now = new Date();
    const date = now.toISOString().split("T")[0];
    const createdAt = now.toISOString();
    const status = payload.status || "published";
    const novel = payload.novel === true;

    const key = `results/${payload.skill}/${date}/${id}.json`;
    const r2Url = `${PUBLIC_BASE_URL}/${key}`;

    // Extract lightweight summary fields from result_data
    const resultData = payload.result_data as Record<string, unknown>;
    const confidenceScore =
        typeof resultData?.confidence_score === "number" ? resultData.confidence_score : null;
    const gene = typeof resultData?.gene === "string" ? resultData.gene : null;

    // Write full result object to R2
    const resultObject = {
        id,
        skill: payload.skill,
        date,
        novel,
        status,
        result_data: payload.result_data,
        created_at: createdAt,
    };

    await env.RESULTS_BUCKET.put(key, JSON.stringify(resultObject, null, 2), {
        httpMetadata: { contentType: "application/json" },
    });

    // Insert index row into D1
    await env.RESULTS_DB.prepare(
        `INSERT INTO results
       (id, skill, date, novel, status, r2_url, confidence_score, gene, contributor_id, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
        .bind(
            id,
            payload.skill,
            date,
            novel ? 1 : 0,
            status,
            r2Url,
            confidenceScore,
            gene,
            payload.contributor_id ?? null,
            createdAt
        )
        .run();

    // Update rolling latest.json
    await updateLatest(env, { id, skill: payload.skill, date, novel, status, url: r2Url, confidence_score: confidenceScore, gene, created_at: createdAt });

    return json({ id, url: r2Url }, 201);
}

// ── GET /results ──────────────────────────────────────────────────────────────

async function handleGet(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const skill = url.searchParams.get("skill");
    const date = url.searchParams.get("date");
    const novelParam = url.searchParams.get("novel");
    const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "50", 10), 200);

    let query =
        "SELECT id, skill, date, novel, status, r2_url, confidence_score, gene, created_at FROM results WHERE 1=1";
    const bindings: (string | number)[] = [];

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

    query += " ORDER BY created_at DESC LIMIT ?";
    bindings.push(limit);

    const result = await env.RESULTS_DB.prepare(query)
        .bind(...bindings)
        .all();

    return json({ results: result.results, count: result.results.length });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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

function json(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
        status,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
    });
}
