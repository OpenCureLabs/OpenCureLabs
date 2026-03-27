/**
 * OpenCure Labs — Ingest Worker Tests
 *
 * Tests auth, rate limiting, error handling, JSON validation,
 * task lifecycle, and CORS headers using Miniflare.
 */
import { Miniflare } from "miniflare";
import { describe, it, expect, beforeAll, afterAll, beforeEach } from "vitest";

let mf: Miniflare;

beforeAll(async () => {
    mf = new Miniflare({
        modules: true,
        scriptPath: "./dist/index.mjs",
        compatibilityDate: "2026-01-01",
        d1Databases: { RESULTS_DB: "test-db" },
        r2Buckets: { RESULTS_BUCKET: "test-bucket" },
        bindings: { ADMIN_KEY: "test-admin-key-secret" },
    });
    await mf.ready;
    const db = await mf.getD1Database("RESULTS_DB");
    await db.batch([
        db.prepare("CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, skill TEXT NOT NULL, date TEXT NOT NULL, novel INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'published', r2_url TEXT NOT NULL, species TEXT NOT NULL DEFAULT 'human', confidence_score REAL, gene TEXT, contributor_id TEXT, reviewed_at TEXT, created_at TEXT NOT NULL)"),
        db.prepare("CREATE TABLE IF NOT EXISTS critiques (id TEXT PRIMARY KEY, result_id TEXT NOT NULL, reviewer TEXT NOT NULL, overall_score REAL, recommendation TEXT, critique_data TEXT NOT NULL, r2_url TEXT, created_at TEXT NOT NULL)"),
        db.prepare("CREATE TABLE IF NOT EXISTS contributors (contributor_id TEXT PRIMARY KEY, public_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)"),
        db.prepare("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, skill TEXT NOT NULL, input_hash TEXT NOT NULL UNIQUE, input_data TEXT NOT NULL, domain TEXT, species TEXT DEFAULT 'human', label TEXT, priority INTEGER DEFAULT 5, status TEXT DEFAULT 'available', claimed_by TEXT, claimed_at TEXT, completed_at TEXT, result_id TEXT, failure_reason TEXT, failed_at TEXT, failure_count INTEGER DEFAULT 0, source TEXT DEFAULT 'bank', parent_result_id TEXT, parent_task_id TEXT, chain_id TEXT, chain_step INTEGER DEFAULT 0, created_at TEXT NOT NULL)"),
    ]);
});

afterAll(async () => {
    await mf.dispose();
});

beforeEach(async () => {
    const db = await mf.getD1Database("RESULTS_DB");
    await db.batch([
        db.prepare("DELETE FROM critiques"),
        db.prepare("DELETE FROM results"),
        db.prepare("DELETE FROM contributors"),
        db.prepare("DELETE FROM tasks"),
    ]);
});

async function send(
    path: string,
    init?: RequestInit & { headers?: Record<string, string> },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Promise<any> {
    return mf.dispatchFetch(`http://localhost${path}`, {
        ...init,
        headers: {
            "Content-Type": "application/json",
            ...(init?.headers ?? {}),
        },
    } as any);
}

describe("CORS", () => {
    it("returns CORS headers on OPTIONS", async () => {
        const resp = await send("/results", { method: "OPTIONS" });
        expect(resp.status).toBe(200);
        expect(resp.headers.get("Access-Control-Allow-Origin")).toBe("*");
    });

    it("JSON responses include CORS headers", async () => {
        const resp = await send("/results");
        expect(resp.headers.get("Access-Control-Allow-Origin")).toBe("*");
    });
});

describe("Admin Auth", () => {
    it("POST /tasks/generate returns 401 without admin key", async () => {
        const resp = await send("/tasks/generate", { method: "POST" });
        expect(resp.status).toBe(401);
        const body = (await resp.json()) as { error: string };
        expect(body.error).toBe("Unauthorized");
    });

    it("POST /tasks/generate returns 401 with wrong admin key", async () => {
        const resp = await send("/tasks/generate", {
            method: "POST", headers: { "X-Admin-Key": "wrong-key" },
        });
        expect(resp.status).toBe(401);
    });

    it("POST /tasks/generate succeeds with correct admin key", async () => {
        const resp = await send("/tasks/generate", {
            method: "POST",
            body: JSON.stringify({ offset: 0, limit: 1 }),
            headers: { "X-Admin-Key": "test-admin-key-secret" },
        });
        expect(resp.status).toBe(200);
        const body = (await resp.json()) as { ok: boolean };
        expect(body.ok).toBe(true);
    });

    it("POST /tasks/recycle returns 401 without admin key", async () => {
        const resp = await send("/tasks/recycle", { method: "POST" });
        expect(resp.status).toBe(401);
    });

    it("POST /tasks/recycle succeeds with correct admin key", async () => {
        const resp = await send("/tasks/recycle", {
            method: "POST",
            body: JSON.stringify({ days: 0 }),
            headers: { "X-Admin-Key": "test-admin-key-secret" },
        });
        expect(resp.status).toBe(200);
        const body = (await resp.json()) as { ok: boolean };
        expect(body.ok).toBe(true);
    });

    it("GET /contributors returns 401 without admin key", async () => {
        const resp = await send("/contributors");
        expect(resp.status).toBe(401);
    });

    it("GET /contributors succeeds with correct admin key", async () => {
        const resp = await send("/contributors", {
            headers: { "X-Admin-Key": "test-admin-key-secret" },
        });
        expect(resp.status).toBe(200);
        const body = (await resp.json()) as { contributors: unknown[] };
        expect(body.contributors).toEqual([]);
    });

    it("PATCH /results/:id returns 401 without admin key", async () => {
        const resp = await send("/results/some-id", {
            method: "PATCH",
        });
        expect(resp.status).toBe(401);
    });
});

describe("Routing", () => {
    it("returns 404 for unknown paths", async () => {
        const resp = await send("/nonexistent");
        expect(resp.status).toBe(404);
    });

    it("returns 404 for wrong method on existing path", async () => {
        const resp = await send("/tasks/stats", { method: "POST", body: "{}" });
        expect(resp.status).toBe(404);
    });
});

describe("POST /contributors", () => {
    const validKey = "a".repeat(64);

    it("registers a new contributor", async () => {
        const resp = await send("/contributors", {
            method: "POST",
            body: JSON.stringify({ contributor_id: "test-1", public_key: validKey }),
        });
        expect(resp.status).toBe(201);
        const body = (await resp.json()) as { contributor_id: string; status: string };
        expect(body.contributor_id).toBe("test-1");
        expect(body.status).toBe("active");
    });

    it("rejects missing fields", async () => {
        const resp = await send("/contributors", {
            method: "POST",
            body: JSON.stringify({ contributor_id: "test-1" }),
        });
        expect(resp.status).toBe(400);
    });

    it("rejects invalid public_key format", async () => {
        const resp = await send("/contributors", {
            method: "POST",
            body: JSON.stringify({ contributor_id: "test-1", public_key: "not-hex" }),
        });
        expect(resp.status).toBe(400);
        const body = (await resp.json()) as { error: string };
        expect(body.error).toMatch(/64-character hex/);
    });

    it("rejects duplicate contributor", async () => {
        const payload = JSON.stringify({ contributor_id: "dupe-1", public_key: validKey });
        await send("/contributors", { method: "POST", body: payload });
        const resp = await send("/contributors", { method: "POST", body: payload });
        expect(resp.status).toBe(409);
    });

    it("rejects malformed JSON", async () => {
        const resp = await send("/contributors", { method: "POST", body: "not json {{" });
        expect(resp.status).toBe(400);
        const body = (await resp.json()) as { error: string };
        expect(body.error).toBe("Invalid JSON body");
    });

    it("returns 429 when rate limit exceeded", async () => {
        for (let i = 0; i < 10; i++) {
            const key = i.toString(16).padStart(64, "0");
            await send("/contributors", {
                method: "POST",
                body: JSON.stringify({ contributor_id: `rate-${i}`, public_key: key }),
            });
        }
        const resp = await send("/contributors", {
            method: "POST",
            body: JSON.stringify({ contributor_id: "rate-10", public_key: "f".repeat(64) }),
        });
        expect(resp.status).toBe(429);
        expect(resp.headers.get("Retry-After")).toBeTruthy();
    });
});

describe("Task Queue", () => {
    async function seedTask(id: string, skill: string, status = "available", priority = 5) {
        const db = await mf.getD1Database("RESULTS_DB");
        await db.prepare(
            `INSERT INTO tasks (id, skill, input_hash, input_data, domain, species, label, priority, status, created_at)
             VALUES (?, ?, ?, ?, 'oncology', 'human', ?, ?, ?, datetime('now'))`,
        ).bind(id, skill, `hash_${id}`, JSON.stringify({ test: true, id }), `task-${id}`, priority, status).run();
    }

    describe("GET /tasks/claim", () => {
        it("returns empty when no tasks available", async () => {
            const resp = await send("/tasks/claim?contributor_id=alice");
            expect(resp.status).toBe(200);
            const body = (await resp.json()) as { tasks: unknown[]; claimed: number };
            expect(body.tasks).toEqual([]);
            expect(body.claimed).toBe(0);
        });

        it("claims available tasks", async () => {
            await seedTask("t1", "neoantigen_prediction");
            await seedTask("t2", "molecular_docking");
            const resp = await send("/tasks/claim?contributor_id=alice&count=5");
            expect(resp.status).toBe(200);
            const body = (await resp.json()) as { tasks: unknown[]; claimed: number };
            expect(body.claimed).toBe(2);
        });

        it("filters by skill", async () => {
            await seedTask("t1", "neoantigen_prediction");
            await seedTask("t2", "molecular_docking");
            const resp = await send("/tasks/claim?contributor_id=bob&skill=molecular_docking&count=10");
            const body = (await resp.json()) as { tasks: Array<{ skill: string }>; claimed: number };
            expect(body.claimed).toBe(1);
            expect(body.tasks[0].skill).toBe("molecular_docking");
        });

        it("does not double-claim already claimed tasks", async () => {
            await seedTask("t1", "qsar", "claimed");
            const resp = await send("/tasks/claim?contributor_id=charlie");
            const body = (await resp.json()) as { claimed: number };
            expect(body.claimed).toBe(0);
        });

        it("rejects invalid count", async () => {
            const resp = await send("/tasks/claim?contributor_id=x&count=0");
            expect(resp.status).toBe(400);
        });
    });

    describe("POST /tasks/:id/complete", () => {
        it("marks a claimed task as completed", async () => {
            await seedTask("tc1", "qsar", "claimed");
            const resp = await send("/tasks/tc1/complete", {
                method: "POST",
                body: JSON.stringify({ result_id: "res-123" }),
            });
            expect(resp.status).toBe(200);
            const body = (await resp.json()) as { ok: boolean; task_id: string };
            expect(body.ok).toBe(true);
            expect(body.task_id).toBe("tc1");
        });

        it("returns 404 for non-claimed task", async () => {
            await seedTask("tc2", "qsar", "available");
            const resp = await send("/tasks/tc2/complete", {
                method: "POST",
                body: JSON.stringify({ result_id: "res-456" }),
            });
            expect(resp.status).toBe(404);
        });

        it("returns 400 for malformed JSON", async () => {
            const resp = await send("/tasks/tc1/complete", { method: "POST", body: "{{invalid" });
            expect(resp.status).toBe(400);
            const body = (await resp.json()) as { error: string };
            expect(body.error).toBe("Invalid JSON body");
        });
    });

    describe("POST /tasks/:id/fail", () => {
        it("returns task to available on first failure", async () => {
            await seedTask("tf1", "qsar", "claimed");
            const resp = await send("/tasks/tf1/fail", {
                method: "POST",
                body: JSON.stringify({ error: "timeout" }),
            });
            expect(resp.status).toBe(200);
            const body = (await resp.json()) as { status: string; failure_count: number };
            expect(body.status).toBe("available");
            expect(body.failure_count).toBe(1);
        });

        it("permanently fails after 3 attempts", async () => {
            const db = await mf.getD1Database("RESULTS_DB");
            await db.prepare(
                `INSERT INTO tasks (id, skill, input_hash, input_data, status, failure_count, created_at)
                 VALUES ('tf3', 'qsar', 'hash_tf3', '{}', 'claimed', 2, datetime('now'))`,
            ).run();
            const resp = await send("/tasks/tf3/fail", {
                method: "POST",
                body: JSON.stringify({ error: "crash" }),
            });
            expect(resp.status).toBe(200);
            const body = (await resp.json()) as { status: string; failure_count: number };
            expect(body.status).toBe("failed");
            expect(body.failure_count).toBe(3);
        });

        it("returns 400 for malformed JSON", async () => {
            const resp = await send("/tasks/x/fail", { method: "POST", body: "not-json" });
            expect(resp.status).toBe(400);
        });
    });
});

describe("Public endpoints", () => {
    it("GET /tasks/stats returns aggregates", async () => {
        const resp = await send("/tasks/stats");
        expect(resp.status).toBe(200);
        const body = (await resp.json()) as { by_skill: unknown[]; totals: unknown[] };
        expect(Array.isArray(body.by_skill)).toBe(true);
        expect(Array.isArray(body.totals)).toBe(true);
    });

    it("GET /leaderboard returns rankings", async () => {
        const resp = await send("/leaderboard");
        expect(resp.status).toBe(200);
        const body = (await resp.json()) as { leaderboard: unknown[] };
        expect(Array.isArray(body.leaderboard)).toBe(true);
    });

    it("GET /results returns results list", async () => {
        const resp = await send("/results");
        expect(resp.status).toBe(200);
    });

    it("GET /results/count returns counts", async () => {
        const resp = await send("/results/count");
        expect(resp.status).toBe(200);
    });
});

describe("Critiques", () => {
    it("POST /critiques rejects missing fields", async () => {
        const resp = await send("/critiques", {
            method: "POST",
            body: JSON.stringify({ reviewer: "test" }),
        });
        expect(resp.status).toBe(400);
    });

    it("POST /critiques rejects malformed JSON", async () => {
        const resp = await send("/critiques", { method: "POST", body: "broken{json" });
        expect(resp.status).toBe(400);
    });

    it("POST /critiques rejects non-existent result_id", async () => {
        const resp = await send("/critiques", {
            method: "POST",
            body: JSON.stringify({ result_id: "nonexistent", reviewer: "test", critique_data: { score: 5 } }),
        });
        expect(resp.status).toBe(404);
    });

    it("POST /critiques creates critique for existing result", async () => {
        const db = await mf.getD1Database("RESULTS_DB");
        await db.prepare(
            `INSERT INTO results (id, skill, date, novel, status, r2_url, created_at)
             VALUES ('r1', 'qsar', '2026-01-01', 0, 'published', 'https://example.com/r1.json', datetime('now'))`,
        ).run();

        const resp = await send("/critiques", {
            method: "POST",
            body: JSON.stringify({
                result_id: "r1", reviewer: "claude_opus", overall_score: 8.5,
                recommendation: "publish", critique_data: { novelty: 7, rigor: 9 },
            }),
        });
        expect(resp.status).toBe(201);
        const body = (await resp.json()) as { id: string; url: string };
        expect(body.id).toBeTruthy();
        expect(body.url).toMatch(/critiques\/qsar/);
    });

    it("GET /critiques returns list", async () => {
        const resp = await send("/critiques");
        expect(resp.status).toBe(200);
        const body = (await resp.json()) as { critiques: unknown[] };
        expect(Array.isArray(body.critiques)).toBe(true);
    });
});

describe("Task Chains", () => {
    it("GET /tasks/chain/:id returns 404 for unknown chain", async () => {
        const resp = await send("/tasks/chain/00000000-0000-0000-0000-000000000000");
        expect(resp.status).toBe(404);
    });

    it("GET /tasks/chains returns empty list", async () => {
        const resp = await send("/tasks/chains");
        expect(resp.status).toBe(200);
        const body = (await resp.json()) as { chains: unknown[] };
        expect(body.chains).toEqual([]);
    });
});

describe("Error handling", () => {
    it("does not leak stack traces in error responses", async () => {
        const resp = await send("/nonexistent");
        expect(resp.status).toBe(404);
        const body = (await resp.json()) as { error: string };
        expect(body.error).toBe("Not found");
        expect(JSON.stringify(body)).not.toContain("at ");
    });
});
