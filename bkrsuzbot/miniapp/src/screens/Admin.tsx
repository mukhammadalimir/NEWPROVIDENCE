import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../ctx";

/** Админ-панель: доступна только ADMIN_IDS (проверяется на сервере). */
export function AdminScreen() {
  const [tab, setTab] = useState<"stats" | "reports" | "dict">("stats");
  return (
    <div className="screen">
      <div className="segmented">
        {(["stats", "reports", "dict"] as const).map((k) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {k === "stats" ? "Statistika" : k === "reports" ? "Xabarlar" : "Lug‘at"}
          </button>
        ))}
      </div>
      {tab === "stats" && <Stats />}
      {tab === "reports" && <Reports />}
      {tab === "dict" && <Dict />}
    </div>
  );
}

function Stats() {
  const [s, setS] = useState<any>(null);
  useEffect(() => { api.admin.stats().then(setS).catch(() => setS({ error: true })); }, []);
  if (!s) return <div className="card skeleton"><div className="sk sk-line w80" /></div>;
  if (s.error) return <div className="notice warn">Xatolik</div>;
  const toggle = async (k: string) => setS({ ...s, flags: await api.admin.flags({ [k]: !s.flags[k] }) });
  return (
    <>
      <div className="card">
        <div className="stat-grid">
          <div><b>{s.users_total}</b><span>foydalanuvchi</span></div>
          <div><b>{s.users_active}</b><span>faol ({s.days} kun)</span></div>
          <div><b>{s.reports_new}</b><span>yangi xabar</span></div>
        </div>
        <ul className="svc">
          {Object.entries(s.services as Record<string, { ok: number; error: number }>).map(([k, v]) => (
            <li key={k}><span>{k}</span><b>✅ {v.ok} · ❌ {v.error}</b></li>
          ))}
        </ul>
      </div>
      <div className="card">
        <div className="block-title">Funksiyalar</div>
        <ul className="svc">
          {Object.entries(s.flags as Record<string, boolean>).map(([k, on]) => (
            <li key={k}>
              <span>{k} {k in s.configured && !s.configured[k] && <em className="hint">(kalit yo‘q)</em>}</span>
              <button className={`switch ${on ? "on" : ""}`} onClick={() => toggle(k)} aria-pressed={on}><i /></button>
            </li>
          ))}
        </ul>
      </div>
      {s.last_errors.length > 0 && (
        <div className="card">
          <div className="block-title">Oxirgi xatolar</div>
          {s.last_errors.map((e: any, i: number) => <p key={i} className="hint">{e.service}: {e.detail}</p>)}
        </div>
      )}
    </>
  );
}

function Reports() {
  const [items, setItems] = useState<any[] | null>(null);
  useEffect(() => { api.admin.reports().then(setItems).catch(() => setItems([])); }, []);
  if (!items) return <div className="card skeleton"><div className="sk sk-line w80" /></div>;
  if (!items.length) return <p className="hint center">Yangi xabarlar yo‘q</p>;
  return (
    <>
      {items.map((r) => (
        <div key={r.id} className="card">
          <div className="block-title">#{r.id} · «{r.query}» · user {r.user_id}</div>
          <p>{r.message}</p>
          <button className="btn secondary" onClick={async () => {
            await api.admin.resolve(r.id);
            setItems(items.filter((x) => x.id !== r.id));
          }}>Hal qilindi</button>
        </div>
      ))}
    </>
  );
}

const lines = (s: string) => s.split("\n").map((l) => l.split("|").map((x) => x.trim())).filter((p) => p[0]);
const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

function toForm(e: any) {
  return {
    id: e.source === "curated" ? e.id : null,
    simplified: e.simplified, traditional: e.traditional, pinyin: e.pinyin,
    measure_word: e.measure_word ?? "", verified: e.source === "curated" ? e.verified : true,
    senses: (e.senses as any[]).filter((s) => s.uz || s.ru)
      .map((s) => [typeof s.pos === "object" ? s.pos?.uz ?? "" : s.pos ?? "", (s.uz ?? []).join(", "), (s.ru ?? []).join(", ")].join(" | ")).join("\n"),
    usage_uz: e.usage?.uz ?? "", usage_ru: e.usage?.ru ?? "",
    examples: (e.examples as any[]).map((x) => [x.zh, x.uz ?? "", x.ru ?? ""].join(" | ")).join("\n"),
    collocations: (e.collocations as any[]).map((x) => [x.zh, x.pinyin ?? "", x.uz ?? "", x.ru ?? ""].join(" | ")).join("\n"),
    english: (e.senses as any[]).flatMap((s) => s.en ?? []).join("; "),
  };
}

function Dict() {
  const { toast } = useApp();
  const [q, setQ] = useState("");
  const [entries, setEntries] = useState<any[]>([]);
  const [form, setForm] = useState<ReturnType<typeof toForm> | null>(null);

  const find = async () => setEntries(await api.admin.entries(q.trim()));
  const save = async () => {
    if (!form) return;
    const body = {
      simplified: form.simplified, traditional: form.traditional || null, pinyin: form.pinyin,
      measure_word: form.measure_word || null, verified: form.verified,
      senses: lines(form.senses).map(([pos, uz, ru]) => ({ pos: pos ? { uz: pos, ru: pos } : null, uz: list(uz ?? ""), ru: list(ru ?? "") })),
      usage: { ...(form.usage_uz && { uz: form.usage_uz }), ...(form.usage_ru && { ru: form.usage_ru }) },
      examples: lines(form.examples).map(([zh, uz, ru]) => ({ zh, uz, ru })),
      collocations: lines(form.collocations).map(([zh, pinyin, uz, ru]) => ({ zh, pinyin, uz, ru })),
    };
    try {
      if (form.id) await api.admin.update(form.id, body); else await api.admin.create(body);
      toast("Saqlandi");
      setForm(null);
      find();
    } catch {
      toast("Xatolik: maydonlarni tekshiring");
    }
  };

  if (form) {
    const f = (k: keyof typeof form, label: string, area = false) => (
      <>
        <label>{label}</label>
        {area ? <textarea className="input" rows={3} value={String(form[k] ?? "")} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
          : <input className="input" value={String(form[k] ?? "")} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />}
      </>
    );
    return (
      <div className="card settings">
        <div className="block-title">{form.id ? `Tahrirlash #${form.id}` : "Yangi tahririyat kartasi"}</div>
        {form.english && <p className="hint">CC-CEDICT: {form.english}</p>}
        {f("simplified", "Soddalashgan")}
        {f("traditional", "An’anaviy")}
        {f("pinyin", "Pinyin (raqamlar bilan: yu2, ni3 hao3)")}
        {f("measure_word", "Sanoq so‘zi")}
        {f("senses", "Ma’nolar: har qatorda «so‘z turkumi | uz1, uz2 | ru1, ru2»", true)}
        {f("usage_uz", "Qo‘llanilishi (uz)", true)}
        {f("usage_ru", "Употребление (ru)", true)}
        {f("collocations", "Birikmalar: «汉字 | pinyin | uz | ru»", true)}
        {f("examples", "Misollar: «汉字句子 | uz | ru» (pinyin avtomatik)", true)}
        <label className="check"><input type="checkbox" checked={form.verified} onChange={(e) => setForm({ ...form, verified: e.target.checked })} /> Tekshirilgan</label>
        <div className="sheet-actions">
          <button className="btn secondary" onClick={() => setForm(null)}>Bekor qilish</button>
          <button className="btn" onClick={save}>Saqlash</button>
        </div>
        {form.id && <button className="btn danger wide" onClick={async () => { await api.admin.remove(form.id!); setForm(null); find(); }}>O‘chirish</button>}
      </div>
    );
  }

  return (
    <>
      <form className="search" onSubmit={(e) => { e.preventDefault(); find(); }}>
        <div className="search-box"><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ierogliflar: 鱼" /></div>
        <button className="btn wide" disabled={!q.trim()}>Topish</button>
      </form>
      {entries.map((e) => (
        <div key={e.id} className="card">
          <div className="block-title">{e.source === "curated" ? (e.verified ? "✅ tahririyat" : "✍️ tahririyat") : "📖 CC-CEDICT"} · {e.pinyin}</div>
          <p><b lang="zh-CN">{e.simplified}</b> {e.senses.map((s: any) => (s.uz ?? s.en ?? []).join(", ")).join("; ")}</p>
          <button className="btn secondary" onClick={() => setForm(toForm(e))}>
            {e.source === "curated" ? "Tahrirlash" : "Tahririyat kartasini yaratish"}
          </button>
        </div>
      ))}
      <button className="btn secondary wide" onClick={() => setForm(toForm({ simplified: q, traditional: "", pinyin: "", senses: [], examples: [], collocations: [], source: "new" }))}>
        + Yangi karta
      </button>
    </>
  );
}
