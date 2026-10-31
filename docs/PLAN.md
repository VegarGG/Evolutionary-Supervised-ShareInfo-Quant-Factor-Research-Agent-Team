<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="QFR Implementation Plan v2: an owner-driven, MCP-fronted multi-agent quantitative factor research and evolution system with traceable factor development, pervasive logging, Kimi/GLM/DeepSeek research providers and a Docker Compose deployment on an Apple silicon Mac Studio.">
<title>QFR Implementation Plan v2 · Owner-driven through MCP</title>
<style>
/* ==========================================================================
   QFR Implementation Plan v2 — self-contained document theme
   Light + dark, print-ready, no external assets.
   ========================================================================== */
:root{
  --font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
  --font-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --bg:#f5f7fb;
  --bg-image:radial-gradient(1200px 600px at 12% -10%,rgba(99,102,241,.10),transparent 60%),radial-gradient(900px 500px at 100% 0%,rgba(16,185,129,.07),transparent 55%);
  --panel:#ffffff;--panel-2:#f8fafc;--panel-3:#f1f5f9;
  --ink:#0b1220;--ink-2:#33415c;--muted:#64748b;--muted-2:#94a3b8;
  --line:#e6ebf4;--line-strong:#d5deea;
  --accent:#4f46e5;--accent-2:#6366f1;--accent-ink:#3730a3;--accent-soft:#eef2ff;--accent-soft-2:#e0e7ff;
  --green:#059669;--green-soft:#ecfdf5;--green-line:#a7f3d0;
  --amber:#b45309;--amber-soft:#fffbeb;--amber-line:#fde68a;
  --red:#dc2626;--red-soft:#fef2f2;--red-line:#fecaca;
  --teal:#0f766e;--teal-soft:#f0fdfa;
  --code-bg:#0b1220;--code-ink:#dbe4f5;
  --shadow-xs:0 1px 2px rgba(15,23,42,.05);
  --shadow-sm:0 1px 3px rgba(15,23,42,.07),0 1px 2px rgba(15,23,42,.04);
  --shadow:0 18px 40px -24px rgba(15,23,42,.28);
  --radius-xs:8px;--radius-sm:10px;--radius:14px;--radius-lg:20px;
  --topbar-h:58px;--maxw:1460px;
  /* diagram palette */
  --d-research:#eaf2ff;--d-research-line:#5274a8;--d-research-ink:#18304f;
  --d-store:#f1ecfa;--d-store-line:#80659e;--d-store-ink:#36244b;
  --d-eval:#e8f4ed;--d-eval-line:#4c8566;--d-eval-ink:#173b29;
  --d-feedback:#fff3d9;--d-feedback-line:#ab8535;--d-feedback-ink:#4c3912;
  --d-control:#fdf2f8;--d-control-line:#a8577f;--d-control-ink:#4a1d33;
  --d-logs:#f4f4f5;--d-logs-line:#71717a;--d-logs-ink:#18181b;
  --d-edge:#475569;--d-edge-soft:#94a3b8;
  color-scheme:light;
}
[data-theme="dark"]{
  --bg:#070b14;
  --bg-image:radial-gradient(1100px 560px at 10% -10%,rgba(99,102,241,.18),transparent 60%),radial-gradient(900px 500px at 100% 0%,rgba(16,185,129,.10),transparent 55%);
  --panel:#0d1424;--panel-2:#111a2e;--panel-3:#16203a;
  --ink:#eaf0fb;--ink-2:#c3cee3;--muted:#92a1bc;--muted-2:#6b7c9c;
  --line:#1c2740;--line-strong:#2a3854;
  --accent:#818cf8;--accent-2:#a5b4fc;--accent-ink:#c7d2fe;--accent-soft:#161f3b;--accent-soft-2:#1c2850;
  --green:#34d399;--green-soft:#0c2a24;--green-line:#1f5c4c;
  --amber:#fbbf24;--amber-soft:#2a2110;--amber-line:#5a4512;
  --red:#f87171;--red-soft:#2a1414;--red-line:#5c2323;
  --teal:#2dd4bf;--teal-soft:#0b2622;
  --code-bg:#05080f;--code-ink:#d7e2f7;
  --shadow-xs:0 1px 2px rgba(0,0,0,.4);--shadow-sm:0 1px 3px rgba(0,0,0,.45);--shadow:0 20px 44px -24px rgba(0,0,0,.75);
  --d-research:#13223a;--d-research-line:#6b8fc7;--d-research-ink:#d7e4fb;
  --d-store:#241c33;--d-store-line:#a088c2;--d-store-ink:#e7dcf7;
  --d-eval:#10281d;--d-eval-line:#5fa883;--d-eval-ink:#d3f1df;
  --d-feedback:#2b2210;--d-feedback-line:#c7a04e;--d-feedback-ink:#fbe9c2;
  --d-control:#2d1623;--d-control-line:#c879a3;--d-control-ink:#fbdcea;
  --d-logs:#1a1b20;--d-logs-line:#8b8d95;--d-logs-ink:#e6e7ea;
  --d-edge:#b7c3d6;--d-edge-soft:#6b7c9c;
  color-scheme:dark;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]):not([data-theme="dark"]){
    --bg:#070b14;
    --bg-image:radial-gradient(1100px 560px at 10% -10%,rgba(99,102,241,.18),transparent 60%),radial-gradient(900px 500px at 100% 0%,rgba(16,185,129,.10),transparent 55%);
    --panel:#0d1424;--panel-2:#111a2e;--panel-3:#16203a;
    --ink:#eaf0fb;--ink-2:#c3cee3;--muted:#92a1bc;--muted-2:#6b7c9c;
    --line:#1c2740;--line-strong:#2a3854;
    --accent:#818cf8;--accent-2:#a5b4fc;--accent-ink:#c7d2fe;--accent-soft:#161f3b;--accent-soft-2:#1c2850;
    --green:#34d399;--green-soft:#0c2a24;--green-line:#1f5c4c;
    --amber:#fbbf24;--amber-soft:#2a2110;--amber-line:#5a4512;
    --red:#f87171;--red-soft:#2a1414;--red-line:#5c2323;
    --teal:#2dd4bf;--teal-soft:#0b2622;
    --code-bg:#05080f;--code-ink:#d7e2f7;
    --shadow-xs:0 1px 2px rgba(0,0,0,.4);--shadow-sm:0 1px 3px rgba(0,0,0,.45);--shadow:0 20px 44px -24px rgba(0,0,0,.75);
    --d-research:#13223a;--d-research-line:#6b8fc7;--d-research-ink:#d7e4fb;
    --d-store:#241c33;--d-store-line:#a088c2;--d-store-ink:#e7dcf7;
    --d-eval:#10281d;--d-eval-line:#5fa883;--d-eval-ink:#d3f1df;
    --d-feedback:#2b2210;--d-feedback-line:#c7a04e;--d-feedback-ink:#fbe9c2;
    --d-control:#2d1623;--d-control-line:#c879a3;--d-control-ink:#fbdcea;
    --d-logs:#1a1b20;--d-logs-line:#8b8d95;--d-logs-ink:#e6e7ea;
    --d-edge:#b7c3d6;--d-edge-soft:#6b7c9c;
    color-scheme:dark;
  }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:calc(var(--topbar-h) + 18px);-webkit-text-size-adjust:100%}
body{margin:0;font-family:var(--font-sans);font-size:16px;line-height:1.72;color:var(--ink);background:var(--bg);background-image:var(--bg-image);background-attachment:fixed;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
::selection{background:rgba(99,102,241,.22)}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:2px}
.skip-link{position:absolute;left:12px;top:-60px;z-index:200;padding:10px 16px;border-radius:0 0 10px 10px;background:var(--accent);color:#fff;font-weight:600}
.skip-link:focus{top:0}

/* topbar */
.topbar{position:fixed;inset:0 0 auto 0;z-index:90;height:var(--topbar-h);display:flex;align-items:center;gap:14px;padding:0 20px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--panel) 84%,transparent);backdrop-filter:saturate(180%) blur(14px);-webkit-backdrop-filter:saturate(180%) blur(14px)}
.brand{display:inline-flex;align-items:center;gap:10px;color:var(--ink);font-weight:700;letter-spacing:-.01em;white-space:nowrap}
.brand:hover{text-decoration:none}
.brand-mark{width:30px;height:30px;border-radius:9px;background:linear-gradient(140deg,#6366f1 0%,#4338ca 52%,#0f766e 100%);display:grid;place-items:center;box-shadow:0 4px 12px -4px rgba(79,70,229,.6)}
.brand-mark svg{width:18px;height:18px;display:block}
.brand-text{font-size:14px;line-height:1.1}
.brand-text small{display:block;margin-top:2px;font-size:10.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.topnav{display:flex;align-items:center;gap:2px;margin-left:4px}
.topnav a{display:inline-block;padding:7px 10px;border-radius:8px;color:var(--muted);font-size:13px;font-weight:600}
.topnav a:hover{color:var(--ink);background:var(--panel-3);text-decoration:none}
.topbar-spacer{flex:1}
.topbar-actions{display:flex;align-items:center;gap:8px}
.search{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:var(--panel)}
.search input{border:0;outline:0;background:transparent;color:var(--ink);font:inherit;font-size:13px;width:190px}
.search svg{width:15px;height:15px;color:var(--muted)}
.icon-btn{appearance:none;border:1px solid var(--line);background:var(--panel);color:var(--ink-2);height:34px;min-width:34px;padding:0 10px;border-radius:9px;display:inline-flex;align-items:center;justify-content:center;gap:7px;font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;transition:background .15s,border-color .15s,color .15s}
.icon-btn:hover{background:var(--panel-3);border-color:var(--line-strong);color:var(--ink)}
.icon-btn svg{width:16px;height:16px;display:block}
.read-progress{position:absolute;left:0;right:0;bottom:-1px;height:2px;pointer-events:none}
.read-progress span{display:block;height:100%;width:0;background:linear-gradient(90deg,#6366f1,#22d3ee 55%,#34d399)}
@media (max-width:1100px){.topnav{display:none}.search input{width:120px}}
@media (max-width:720px){.search{display:none}.brand-text small{display:none}.icon-btn{padding:0;min-width:34px}.icon-btn span,.icon-btn .btn-text{display:none}.topbar{gap:8px;padding:0 12px}}

/* hero */
.hero{position:relative;margin-top:var(--topbar-h);overflow:hidden;color:#f4f6ff;background:radial-gradient(900px 480px at 12% 8%,rgba(99,102,241,.42),transparent 62%),radial-gradient(760px 420px at 88% -4%,rgba(13,148,136,.34),transparent 58%),radial-gradient(600px 360px at 60% 110%,rgba(56,189,248,.16),transparent 60%),linear-gradient(155deg,#0a1020 0%,#131a36 46%,#0a1628 100%)}
.hero::before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px);background-size:46px 46px;-webkit-mask-image:radial-gradient(ellipse 80% 70% at 50% 0%,#000 35%,transparent 78%);mask-image:radial-gradient(ellipse 80% 70% at 50% 0%,#000 35%,transparent 78%);pointer-events:none}
.hero::after{content:"";position:absolute;inset:auto 0 0 0;height:90px;background:linear-gradient(to bottom,transparent,var(--bg));pointer-events:none}
.hero-inner{position:relative;z-index:1;max-width:var(--maxw);margin:0 auto;padding:60px 40px 100px}
.eyebrow{display:inline-flex;align-items:center;gap:9px;padding:6px 13px 6px 9px;border-radius:999px;border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06);color:#dbe3ff;font-size:12px;font-weight:600}
.eyebrow .dot{width:7px;height:7px;border-radius:50%;background:#34d399;box-shadow:0 0 0 4px rgba(52,211,153,.16)}
.hero h1{margin:22px 0 0;max-width:26ch;font-size:clamp(30px,4.2vw,50px);line-height:1.08;letter-spacing:-.025em;font-weight:800}
.hero h1 span{color:#a5b4fc}
.hero .lede{margin:22px 0 0;max-width:78ch;font-size:17px;line-height:1.65;color:#c9d3ee}
.hero-meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:999px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);color:#e2e8ff;font-size:12.5px;font-weight:600}
.hero-cta{display:flex;flex-wrap:wrap;gap:10px;margin-top:26px}
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 16px;border-radius:11px;font-weight:700;font-size:14px;border:1px solid transparent;cursor:pointer;font-family:inherit}
.btn-primary{background:#fff;color:#1e1b4b}
.btn-primary:hover{background:#eef2ff;text-decoration:none}
.btn-ghost{background:rgba(255,255,255,.08);color:#fff;border-color:rgba(255,255,255,.22)}
.btn-ghost:hover{background:rgba(255,255,255,.14);text-decoration:none}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin-top:40px}
.stat{padding:14px 16px;border-radius:14px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12)}
.stat b{display:block;font-size:24px;letter-spacing:-.02em;color:#fff}
.stat span{font-size:12px;color:#aab6d8;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
@media (max-width:980px){.stats{grid-template-columns:repeat(3,1fr)}}
@media (max-width:560px){.stats{grid-template-columns:repeat(2,1fr)}.hero-inner{padding:44px 20px 80px}}

/* layout */
.layout{max-width:var(--maxw);margin:0 auto;padding:0 40px 80px;display:grid;grid-template-columns:290px minmax(0,1fr);gap:40px;align-items:start}
@media (max-width:1100px){.layout{grid-template-columns:1fr;padding:0 20px 60px}}
.toc{position:sticky;top:calc(var(--topbar-h) + 18px);max-height:calc(100vh - var(--topbar-h) - 36px);overflow:auto;padding:14px 10px 18px 0;scrollbar-width:thin}
.toc h2{margin:0 0 10px 12px;font-size:11.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.toc ol{list-style:none;margin:0;padding:0}
.toc li a{display:block;padding:5px 12px;border-radius:8px;font-size:13.2px;color:var(--ink-2);line-height:1.4}
.toc li a:hover{background:var(--panel-3);text-decoration:none;color:var(--ink)}
.toc li.l3 a{padding-left:28px;font-size:12.4px;color:var(--muted)}
.toc li a.active{background:var(--accent-soft);color:var(--accent-ink);font-weight:600}
.toc li.hide{display:none}
.toc .toc-empty{display:none;margin:8px 12px;color:var(--muted);font-size:13px}
.toc.filtering .toc-empty.show{display:block}
@media (max-width:1100px){.toc{position:static;max-height:none;padding:18px;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel)}}

main{min-width:0}
.chapter{margin:0 0 52px;padding:34px 38px 30px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-lg);box-shadow:var(--shadow-sm)}
@media (max-width:720px){.chapter{padding:24px 18px}}
.chapter-kicker{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.chapter-kicker .n{display:inline-grid;place-items:center;min-width:26px;height:26px;padding:0 7px;border-radius:8px;background:var(--accent-soft);color:var(--accent-ink);font-size:12.5px;letter-spacing:0}
.chapter-kicker .tag{padding:2px 8px;border-radius:999px;background:var(--panel-3);color:var(--muted);font-size:10.5px;letter-spacing:.06em}
.chapter-kicker .tag.new{background:var(--green-soft);color:var(--green)}
.chapter-kicker .tag.changed{background:var(--amber-soft);color:var(--amber)}
h2{margin:10px 0 14px;font-size:30px;line-height:1.15;letter-spacing:-.022em;font-weight:800}
h3{margin:34px 0 10px;font-size:19.5px;letter-spacing:-.012em;font-weight:750;padding-top:6px}
h3 .sn{color:var(--muted);font-weight:600;margin-right:8px}
h4{margin:22px 0 8px;font-size:15.5px;font-weight:700}
h2 .anchor,h3 .anchor{margin-left:8px;color:var(--muted-2);font-weight:500;opacity:0;transition:opacity .15s}
h2:hover .anchor,h3:hover .anchor{opacity:1}
p{margin:0 0 14px}
p,li,td,figcaption{overflow-wrap:anywhere}
.lead{font-size:17px;color:var(--ink-2)}
ul,ol{margin:0 0 14px;padding-left:24px}
li{margin:4px 0}
li>ul,li>ol{margin-top:4px}
code{font-family:var(--font-mono);font-size:.86em;background:var(--panel-3);padding:1px 6px;border-radius:6px;color:var(--ink);overflow-wrap:anywhere}
pre{margin:14px 0 18px;padding:16px 18px;border-radius:var(--radius-sm);background:var(--code-bg);color:var(--code-ink);overflow:auto;font-size:12.8px;line-height:1.6;border:1px solid rgba(255,255,255,.06)}
pre code{background:transparent;padding:0;color:inherit;font-size:inherit}
strong{font-weight:700}
hr{border:0;border-top:1px solid var(--line);margin:28px 0}
.kw{font-weight:800;letter-spacing:.02em}
.table-wrap{overflow:auto;margin:14px 0 20px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel)}
table{width:100%;border-collapse:collapse;font-size:14px;line-height:1.5}
thead th{text-align:left;font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);background:var(--panel-2);padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--panel-2) 60%,transparent)}
td code{white-space:normal;overflow-wrap:anywhere}
.table-wrap.matrix table{font-size:12.6px;line-height:1.45}
.table-wrap.matrix th:first-child,.table-wrap.matrix td:first-child{min-width:92px}
.table-wrap.matrix td:last-child{background:color-mix(in srgb,var(--accent-soft) 55%,transparent)}
td.id,th.id{white-space:nowrap;font-family:var(--font-mono);font-size:12.5px;color:var(--accent-ink)}
.table-wrap.compact table{font-size:13px}
.callout{display:grid;grid-template-columns:auto 1fr;gap:12px;margin:16px 0 20px;padding:14px 16px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--panel-2)}
.callout .ico{width:22px;height:22px;display:grid;place-items:center;border-radius:7px;font-size:12px;font-weight:800;color:#fff;background:var(--accent)}
.callout.rule{background:var(--accent-soft);border-color:var(--accent-soft-2)}
.callout.rule .ico{background:var(--accent)}
.callout.warn{background:var(--amber-soft);border-color:var(--amber-line)}
.callout.warn .ico{background:var(--amber)}
.callout.ok{background:var(--green-soft);border-color:var(--green-line)}
.callout.ok .ico{background:var(--green)}
.callout.stop{background:var(--red-soft);border-color:var(--red-line)}
.callout.stop .ico{background:var(--red)}
.callout p:last-child{margin-bottom:0}
.callout b.t{display:block;margin-bottom:2px}
.grid-2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:14px 0 18px}
.grid-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:14px 0 18px}
@media (max-width:860px){.grid-2,.grid-3{grid-template-columns:1fr}}
.card{padding:16px 18px;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel-2)}
.card h4{margin:0 0 6px;font-size:15px}
.card p{margin:0;font-size:14px;color:var(--ink-2)}
.card .mini{font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;display:block}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:700;letter-spacing:.02em;vertical-align:middle}
.badge.must{background:var(--red-soft);color:var(--red);border:1px solid var(--red-line)}
.badge.should{background:var(--amber-soft);color:var(--amber);border:1px solid var(--amber-line)}
.badge.may{background:var(--green-soft);color:var(--green);border:1px solid var(--green-line)}
.badge.phase{background:var(--accent-soft);color:var(--accent-ink)}
.badge.new{background:var(--green-soft);color:var(--green)}
.badge.ro{background:var(--panel-3);color:var(--muted)}
.badge.rw{background:var(--amber-soft);color:var(--amber)}
.badge.appr{background:var(--red-soft);color:var(--red)}

/* figures */
figure{margin:18px 0 24px;padding:16px;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel-2)}
figure svg{width:100%;height:auto;display:block}
figcaption{margin-top:10px;font-size:13px;color:var(--muted)}
figcaption b{color:var(--ink-2)}
details.src{margin-top:10px}
details.src summary{cursor:pointer;font-size:13px;color:var(--accent);font-weight:600}
details.src pre{margin-top:10px}
svg text{font-family:var(--font-sans)}
svg .zone{stroke-width:1.2;stroke-dasharray:5 4;rx:14}
svg .zone-title{font-size:13px;font-weight:700;letter-spacing:.02em}
svg .zone.research{fill:var(--d-research);stroke:var(--d-research-line);fill-opacity:.55}
svg .zone.eval{fill:var(--d-eval);stroke:var(--d-eval-line);fill-opacity:.55}
svg .zone.registry{fill:var(--d-store);stroke:var(--d-store-line);fill-opacity:.55}
svg .zone.control{fill:var(--d-control);stroke:var(--d-control-line);fill-opacity:.55}
svg .zone.logs{fill:var(--d-logs);stroke:var(--d-logs-line);fill-opacity:.55}
svg .zt.research{fill:var(--d-research-ink)}
svg .zt.eval{fill:var(--d-eval-ink)}
svg .zt.registry{fill:var(--d-store-ink)}
svg .zt.control{fill:var(--d-control-ink)}
svg .zt.logs{fill:var(--d-logs-ink)}
svg .node rect{rx:9;stroke-width:1.2}
svg .node text{font-size:12.5px;font-weight:650}
svg .node .sub{font-size:10.8px;font-weight:500;opacity:.85}
svg .node.research rect{fill:var(--d-research);stroke:var(--d-research-line)}
svg .node.research text{fill:var(--d-research-ink)}
svg .node.eval rect{fill:var(--d-eval);stroke:var(--d-eval-line)}
svg .node.eval text{fill:var(--d-eval-ink)}
svg .node.store rect{fill:var(--d-store);stroke:var(--d-store-line)}
svg .node.store text{fill:var(--d-store-ink)}
svg .node.feedback rect{fill:var(--d-feedback);stroke:var(--d-feedback-line)}
svg .node.feedback text{fill:var(--d-feedback-ink)}
svg .node.control rect{fill:var(--d-control);stroke:var(--d-control-line)}
svg .node.control text{fill:var(--d-control-ink)}
svg .node.logs rect{fill:var(--d-logs);stroke:var(--d-logs-line)}
svg .node.logs text{fill:var(--d-logs-ink)}
svg .node.human rect{fill:var(--panel);stroke:var(--ink-2)}
svg .node.human text{fill:var(--ink)}
svg .edge{fill:none;stroke:var(--d-edge);stroke-width:1.5;marker-end:url(#arr)}
svg .edge.dashed{stroke-dasharray:5 4;stroke:var(--d-edge-soft);marker-end:url(#arr-soft)}
svg .edge.both{marker-start:url(#arr-start)}
svg .elabel{font-size:10.6px;fill:var(--muted);font-weight:600}
svg .elabel.strong{fill:var(--ink-2)}
svg .lifeline{stroke:var(--line-strong);stroke-width:1.2;stroke-dasharray:4 4}
svg .actor rect{rx:9;fill:var(--panel);stroke:var(--line-strong);stroke-width:1.2}
svg .actor text{font-size:12.5px;font-weight:700;fill:var(--ink)}
svg .msg{stroke:var(--d-edge);stroke-width:1.4;marker-end:url(#arr)}
svg .msg.ret{stroke-dasharray:5 4;stroke:var(--d-edge-soft);marker-end:url(#arr-soft)}
svg .mlabel{font-size:11.2px;fill:var(--ink-2);font-weight:600}
svg .step circle{fill:var(--accent);}
svg .step text{fill:#fff;font-size:11px;font-weight:800}
svg .selfloop{fill:none;stroke:var(--d-edge);stroke-width:1.4;marker-end:url(#arr)}
svg .note rect{fill:var(--d-feedback);stroke:var(--d-feedback-line);rx:6}
svg .note text{font-size:10.5px;fill:var(--d-feedback-ink)}
svg .vol rect{rx:7;fill:var(--panel);stroke:var(--d-store-line);stroke-width:1.1;stroke-dasharray:3 3}
svg .vol text{font-size:11px;fill:var(--ink-2);font-weight:600}
svg .host rect{rx:16;fill:none;stroke:var(--ink-2);stroke-width:1.6}
svg .host text{font-size:14px;font-weight:800;fill:var(--ink)}
svg .vm rect{rx:12;fill:var(--panel-2);stroke:var(--line-strong);stroke-width:1.2}
svg .vm text{font-size:12.5px;font-weight:700;fill:var(--ink-2)}
svg .net rect{rx:10;stroke-width:1.1;stroke-dasharray:4 3}
svg .net text{font-size:11px;font-weight:700}
svg .net.research rect{fill:var(--d-research);stroke:var(--d-research-line);fill-opacity:.5}
svg .net.research text{fill:var(--d-research-ink)}
svg .net.eval rect{fill:var(--d-eval);stroke:var(--d-eval-line);fill-opacity:.5}
svg .net.eval text{fill:var(--d-eval-ink)}
svg .net.registry rect{fill:var(--d-store);stroke:var(--d-store-line);fill-opacity:.5}
svg .net.registry text{fill:var(--d-store-ink)}
svg .net.control rect{fill:var(--d-control);stroke:var(--d-control-line);fill-opacity:.5}
svg .net.control text{fill:var(--d-control-ink)}
svg .svc rect{rx:7;fill:var(--panel);stroke:var(--line-strong);stroke-width:1}
svg .svc text{font-size:11px;font-weight:650;fill:var(--ink)}
svg .svc .sub{font-size:9.6px;font-weight:500;fill:var(--muted)}
svg .ext rect{rx:9;fill:var(--panel);stroke:var(--muted);stroke-width:1.2;stroke-dasharray:6 3}
svg .ext text{font-size:12px;font-weight:700;fill:var(--ink-2)}
svg .ext .sub{font-size:10.5px;font-weight:500;fill:var(--muted)}

/* CSS diagrams */
.flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px;margin:14px 0 8px}
.flow .st{display:flex;flex-direction:column;justify-content:center;min-width:120px;padding:9px 12px;border-radius:10px;border:1px solid var(--line-strong);background:var(--panel);font-size:13px;font-weight:650;line-height:1.3}
.flow .st small{font-weight:500;color:var(--muted);font-size:11.5px}
.flow .st.good{border-color:var(--green-line);background:var(--green-soft)}
.flow .st.bad{border-color:var(--red-line);background:var(--red-soft)}
.flow .st.wait{border-color:var(--amber-line);background:var(--amber-soft)}
.flow .st.owner{border-color:var(--d-control-line);background:var(--d-control)}
.flow .arrow{align-self:center;color:var(--muted-2);font-size:18px;line-height:1}
.ladder{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:12px 0 18px}
@media (max-width:860px){.ladder{grid-template-columns:repeat(2,1fr)}}
.ladder .rung{padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--panel)}
.ladder .rung b{display:block;font-size:14px}
.ladder .rung span{font-size:12.5px;color:var(--muted)}
.ladder .rung.owner{border-color:var(--d-control-line);background:var(--d-control)}
.trace-pipe{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:10px;margin:14px 0 10px}
.trace-pipe .tp{position:relative;padding:12px 12px 12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--panel);font-size:12.6px;line-height:1.45}
.trace-pipe .tp b{display:block;font-size:13px;margin-bottom:4px}
.trace-pipe .tp .who{display:inline-block;margin-bottom:6px;padding:1px 7px;border-radius:999px;font-size:10.5px;font-weight:700;letter-spacing:.03em}
.trace-pipe .tp .who.llm{background:var(--d-research);color:var(--d-research-ink)}
.trace-pipe .tp .who.det{background:var(--d-store);color:var(--d-store-ink)}
.trace-pipe .tp .who.eval{background:var(--d-eval);color:var(--d-eval-ink)}
.trace-pipe .tp .who.own{background:var(--d-control);color:var(--d-control-ink)}
.trace-pipe .tp ul{margin:0;padding-left:16px;color:var(--ink-2)}
.trace-pipe .tp li{margin:1px 0}
.trace-pipe .tp .num{position:absolute;top:-9px;left:-9px;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;font-weight:800;display:grid;place-items:center}

/* roadmap */
.phase{margin:22px 0;padding:20px 22px;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel-2)}
.phase-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 14px;margin-bottom:6px}
.phase-head h3{margin:0;padding:0;font-size:20px}
.phase-head .count{font-size:12.5px;color:var(--muted);font-weight:600}
.phase .goal{margin:6px 0 12px;padding:10px 14px;border-left:3px solid var(--accent);background:var(--panel);border-radius:0 10px 10px 0;font-size:14.5px;color:var(--ink-2)}
.tasks{list-style:none;margin:0;padding:0}
.tasks li{margin:0;padding:7px 0;border-top:1px solid var(--line);display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start}
.tasks li:first-child{border-top:0}
.tasks input[type=checkbox]{width:17px;height:17px;margin:4px 0 0;accent-color:var(--accent);cursor:pointer}
.tasks label{cursor:pointer;font-size:14.5px;line-height:1.55}
.tasks label b{font-family:var(--font-mono);font-size:12.5px;color:var(--accent-ink);margin-right:6px}
.tasks li.done label{color:var(--muted);text-decoration:line-through;text-decoration-color:var(--line-strong)}
.accept{margin-top:14px;padding:12px 14px;border-radius:10px;background:var(--green-soft);border:1px solid var(--green-line)}
.accept b{display:block;font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--green);margin-bottom:4px}
.accept ul{margin:0;padding-left:20px;font-size:14px}
.progress{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin:8px 0 18px;padding:12px 16px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
.progress .bar{flex:1 1 160px;height:8px;border-radius:999px;background:var(--panel-3);overflow:hidden}
.progress .bar span{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),#22d3ee);transition:width .2s}
.progress .num{font-weight:700;font-size:14px;min-width:70px;text-align:right}
.progress button{appearance:none;border:1px solid var(--line);background:var(--panel-2);color:var(--ink-2);font:inherit;font-size:12.5px;font-weight:600;padding:5px 10px;border-radius:8px;cursor:pointer}
.progress button:hover{background:var(--panel-3)}
.roadmap-glance{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0 18px}
@media (max-width:860px){.roadmap-glance{grid-template-columns:1fr}}
.roadmap-glance a{display:block;padding:11px 13px;border-radius:11px;border:1px solid var(--line);background:var(--panel);color:var(--ink);font-size:13.5px;font-weight:600;line-height:1.35}
.roadmap-glance a:hover{border-color:var(--accent);text-decoration:none}
.roadmap-glance a small{display:block;color:var(--muted);font-weight:500;font-size:12px}

/* footer */
.foot{max-width:var(--maxw);margin:0 auto;padding:10px 40px 60px;color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;justify-content:space-between}
.to-top{position:fixed;right:22px;bottom:22px;z-index:80;width:40px;height:40px;border-radius:12px;border:1px solid var(--line);background:var(--panel);color:var(--ink-2);display:grid;place-items:center;box-shadow:var(--shadow-sm);cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s}
.to-top.show{opacity:1;pointer-events:auto}
.to-top svg{width:18px;height:18px}

/* print */
@media print{
  :root{--bg:#fff;--bg-image:none;--panel:#fff;--panel-2:#fafafa;--panel-3:#f3f4f6;--ink:#000;--ink-2:#111;--muted:#444;--line:#ccc;--line-strong:#aaa;color-scheme:light}
  body{background:#fff;font-size:11.5pt}
  .topbar,.toc,.to-top,.hero-cta,.progress button,.search,.topbar-actions{display:none !important}
  .hero{margin-top:0;color:#000;background:#fff;border-bottom:2px solid #000}
  .hero::before,.hero::after{display:none}
  .hero h1,.hero .lede,.stat b{color:#000}
  .hero h1 span{color:#000}
  .chip,.stat{border-color:#999;background:#fff;color:#000}
  .stat span,.eyebrow{color:#333;border-color:#999;background:#fff}
  .layout{display:block;padding:0 10mm}
  .chapter{break-inside:auto;box-shadow:none;border-color:#bbb;padding:14pt 0;border:0;border-top:1px solid #bbb;border-radius:0}
  h2{break-after:avoid;font-size:20pt}
  h3{break-after:avoid}
  .table-wrap,figure,.callout,.card,.phase{break-inside:avoid}
  pre{white-space:pre-wrap;word-break:break-word;background:#f3f4f6;color:#000;border:1px solid #bbb}
  details.src{display:none}
  a{color:#000}
  a[href^="http"]::after{content:" (" attr(href) ")";font-size:9pt;color:#444}
  .foot{display:none}
}
</style>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>

<header class="topbar">
  <a class="brand" href="#top">
    <span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18 L10 11 L14 14 L20 6"/><path d="M15 6h5v5"/></svg></span>
    <span class="brand-text">QFR Implementation Plan<small>v2 · owner-driven through MCP</small></span>
  </a>
  <nav class="topnav" aria-label="Quick links">
    <a href="#ch-1">Overview</a>
    <a href="#s-4-4">Workflow</a>
    <a href="#ch-13">MCP</a>
    <a href="#ch-14">Trace</a>
    <a href="#ch-19">Roadmap</a>
    <a href="#ch-20">Defaults</a>
  </nav>
  <div class="topbar-spacer"></div>
  <div class="topbar-actions">
    <label class="search" title="Filter the table of contents">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="toc-filter" type="search" placeholder="Filter sections" aria-label="Filter sections">
    </label>
    <button class="icon-btn" id="theme-btn" type="button" title="Toggle light / dark theme" aria-label="Toggle theme">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z"/></svg>
      <span id="theme-label">Auto</span>
    </button>
    <button class="icon-btn" type="button" onclick="window.print()" title="Print or save as PDF">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/></svg>
      <span class="btn-text">Print</span>
    </button>
  </div>
  <div class="read-progress" aria-hidden="true"><span id="read-bar"></span></div>
</header>

<section class="hero" id="top">
  <div class="hero-inner">
    <span class="eyebrow"><span class="dot"></span>Version 2.2 · Generated 2026-10-31 · Status: ready for implementation</span>
    <h1>QFR Implementation Plan v2: <span>an owner-driven, MCP-fronted</span> multi-agent factor research and evolution system</h1>
    <p class="lede">QFR is operated by a single human owner who works through a host agent (Codex, Claude Code or any other MCP client) that drives QFR over a standard MCP front door. Research agents run on Kimi, GLM and DeepSeek online APIs. Every factor's development path is recorded step by step so the LLM is no longer a black box. Everything inside the system is logged, and the logs are readable through MCP. Deliverables arrive with their iteration history and backtesting results, the owner approves, and approved factors and strategies are saved to long-lived pools. The system starts with no default factors and no default strategies, and it ships as Docker Compose for an Apple silicon Mac Studio.</p>
    <div class="hero-meta">
      <span class="chip">Standard MCP front door</span>
      <span class="chip">Host agent: Codex · Claude Code · other</span>
      <span class="chip">Providers: Kimi · GLM · DeepSeek</span>
      <span class="chip">Traceable factor evolution</span>
      <span class="chip">Logs everywhere, MCP-readable</span>
      <span class="chip">Docker Compose · linux/arm64 · Mac Studio</span>
      <span class="chip">No default factors or strategies</span>
    </div>
    <div class="hero-cta">
      <a class="btn btn-primary" href="#ch-0">Start reading</a>
      <a class="btn btn-ghost" href="#s-4-4">The owner workflow</a>
      <a class="btn btn-ghost" href="#ch-19">Implementation roadmap</a>
      <a class="btn btn-ghost" href="#" onclick="window.print();return false;">Print / Save as PDF</a>
    </div>
    <div class="stats">
      <div class="stat"><b>24</b><span>Chapters</span></div>
      <div class="stat"><b>9</b><span>Phases</span></div>
      <div class="stat"><b>76</b><span>Tasks</span></div>
      <div class="stat"><b>5</b><span>Figures</span></div>
      <div class="stat"><b>36,744</b><span>Words</span></div>
      <div class="stat"><b>160 min</b><span>Read time</span></div>
    </div>
  </div>
</section>

<div class="layout">
<nav class="toc" aria-label="Table of contents">
  <h2>Contents</h2>
  <ol id="toc-list">
    <li class="l2"><a href="#ch-0">0 How to use this plan</a></li>
    <li class="l2"><a href="#ch-1">1 Executive summary</a></li>
    <li class="l3"><a href="#s-1-1">1.1 What the owner experiences</a></li>
    <li class="l3"><a href="#s-1-2">1.2 How the system is built</a></li>
    <li class="l3"><a href="#s-1-3">1.3 Decisions that make the design robust</a></li>
    <li class="l2"><a href="#ch-2">2 Goals, non-goals and success criteria</a></li>
    <li class="l3"><a href="#s-2-1">2.1 Goals</a></li>
    <li class="l3"><a href="#s-2-2">2.2 Non-goals for v1</a></li>
    <li class="l3"><a href="#s-2-3">2.3 Success criteria for v1</a></li>
    <li class="l2"><a href="#ch-3">3 Design invariants</a></li>
    <li class="l2"><a href="#ch-4">4 Architecture</a></li>
    <li class="l3"><a href="#s-4-1">4.1 System overview</a></li>
    <li class="l3"><a href="#s-4-2">4.2 Components and owners</a></li>
    <li class="l3"><a href="#s-4-3">4.3 Trust boundaries</a></li>
    <li class="l3"><a href="#s-4-4">4.4 The owner workflow end to end</a></li>
    <li class="l3"><a href="#s-4-5">4.5 Key decisions</a></li>
    <li class="l2"><a href="#ch-5">5 Technology stack and repository layout</a></li>
    <li class="l3"><a href="#s-5-1">5.1 Stack</a></li>
    <li class="l3"><a href="#s-5-2">5.2 Repository layout</a></li>
    <li class="l3"><a href="#s-5-3">5.3 Code boundary contracts</a></li>
    <li class="l3"><a href="#s-5-4">5.4 Runtime topology</a></li>
    <li class="l3"><a href="#s-5-5">5.5 Configuration and environment variables</a></li>
    <li class="l2"><a href="#ch-6">6 Market data, data zones and timing conventions</a></li>
    <li class="l3"><a href="#s-6-1">6.1 Sources</a></li>
    <li class="l3"><a href="#s-6-2">6.2 Qlib binary format reader</a></li>
    <li class="l3"><a href="#s-6-3">6.3 Canonical panel</a></li>
    <li class="l3"><a href="#s-6-4">6.4 Data zones and evaluation windows</a></li>
    <li class="l3"><a href="#s-6-5">6.5 Timing conventions</a></li>
    <li class="l3"><a href="#s-6-6">6.6 Synthetic market generator</a></li>
    <li class="l2"><a href="#ch-7">7 Factor DSL and artifact contract</a></li>
    <li class="l3"><a href="#s-7-1">7.1 Why a DSL first</a></li>
    <li class="l3"><a href="#s-7-2">7.2 Grammar</a></li>
    <li class="l3"><a href="#s-7-3">7.3 Operator catalog for v1</a></li>
    <li class="l3"><a href="#s-7-4">7.4 Static constraints</a></li>
    <li class="l3"><a href="#s-7-5">7.5 Canonicalization, hashing and similarity</a></li>
    <li class="l3"><a href="#s-7-6">7.6 Artifact kinds</a></li>
    <li class="l3"><a href="#s-7-7">7.7 Factor manifest (schema version 1)</a></li>
    <li class="l3"><a href="#s-7-8">7.8 Strategy manifest (schema version 1)</a></li>
    <li class="l3"><a href="#s-7-9">7.9 Lifecycle</a></li>
    <li class="l2"><a href="#ch-8">8 Independent evaluation system</a></li>
    <li class="l3"><a href="#s-8-1">8.1 Responsibilities</a></li>
    <li class="l3"><a href="#s-8-2">8.2 Protocol definition</a></li>
    <li class="l3"><a href="#s-8-3">8.3 Intake and eligibility</a></li>
    <li class="l3"><a href="#s-8-4">8.4 Screening</a></li>
    <li class="l3"><a href="#s-8-5">8.5 Factor metrics</a></li>
    <li class="l3"><a href="#s-8-6">8.6 Reference backtest</a></li>
    <li class="l3"><a href="#s-8-7">8.7 Multiple-testing and overfitting statistics</a></li>
    <li class="l3"><a href="#s-8-8">8.8 Gates</a></li>
    <li class="l3"><a href="#s-8-9">8.9 Official records, the trial ledger and owner-grade evidence</a></li>
    <li class="l3"><a href="#s-8-10">8.10 Other kinds: plugins for strategy and research_note</a></li>
    <li class="l2"><a href="#ch-9">9 Feedback release policy and anti-overfitting controls</a></li>
    <li class="l3"><a href="#s-9-1">9.1 Principles</a></li>
    <li class="l3"><a href="#s-9-2">9.2 Release levels for the default_v1 policy</a></li>
    <li class="l3"><a href="#s-9-3">9.3 Quotas</a></li>
    <li class="l3"><a href="#s-9-4">9.4 Burn accounting</a></li>
    <li class="l3"><a href="#s-9-5">9.5 Optional Thresholdout mode for W2 (Phase 8)</a></li>
    <li class="l3"><a href="#s-9-6">9.6 What research is told, and what the owner sees</a></li>
    <li class="l2"><a href="#ch-10">10 Acceptance, simulated trading, pools and promotion</a></li>
    <li class="l3"><a href="#s-10-1">10.1 Flow after W2</a></li>
    <li class="l3"><a href="#s-10-2">10.2 Simulated trading engine</a></li>
    <li class="l3"><a href="#s-10-3">10.3 Acceptance case and gates</a></li>
    <li class="l3"><a href="#s-10-4">10.4 Pools, library and monitoring</a></li>
    <li class="l3"><a href="#s-10-5">10.5 The owner, the host agent and approval records</a></li>
    <li class="l3"><a href="#s-10-6">10.6 Epoch rollover (Phase 8)</a></li>
    <li class="l2"><a href="#ch-11">11 Research system</a></li>
    <li class="l3"><a href="#s-11-1">11.1 Programs, charters and research jobs</a></li>
    <li class="l3"><a href="#s-11-2">11.2 Agent roster</a></li>
    <li class="l3"><a href="#s-11-3">11.3 Tools and permission matrix</a></li>
    <li class="l3"><a href="#s-11-4">11.4 Structured outputs</a></li>
    <li class="l3"><a href="#s-11-5">11.5 Prompting rules</a></li>
    <li class="l3"><a href="#s-11-6">11.6 Generation workflow</a></li>
    <li class="l3"><a href="#s-11-7">11.7 Budget control</a></li>
    <li class="l3"><a href="#s-11-8">11.8 LLM providers: Kimi, GLM and DeepSeek</a></li>
    <li class="l2"><a href="#ch-12">12 Evolutionary engine</a></li>
    <li class="l3"><a href="#s-12-1">12.1 Population structure</a></li>
    <li class="l3"><a href="#s-12-2">12.2 Fitness</a></li>
    <li class="l3"><a href="#s-12-3">12.3 Selection</a></li>
    <li class="l3"><a href="#s-12-4">12.4 Variation operators and default mix</a></li>
    <li class="l3"><a href="#s-12-5">12.5 Inner loop and outer loop</a></li>
    <li class="l3"><a href="#s-12-6">12.6 Budget allocation across islands</a></li>
    <li class="l3"><a href="#s-12-7">12.7 Lineage and trajectories</a></li>
    <li class="l2"><a href="#ch-13">13 MCP front door: the owner&#x27;s control surface</a></li>
    <li class="l3"><a href="#s-13-1">13.1 Role and principles</a></li>
    <li class="l3"><a href="#s-13-2">13.2 Transport, authentication and audit</a></li>
    <li class="l3"><a href="#s-13-3">13.3 Research briefs and jobs</a></li>
    <li class="l3"><a href="#s-13-4">13.4 Deliverables</a></li>
    <li class="l3"><a href="#s-13-5">13.5 Approvals and pool curation</a></li>
    <li class="l3"><a href="#s-13-6">13.6 Setup and the raw factor pool</a></li>
    <li class="l3"><a href="#s-13-7">13.7 Tool catalog</a></li>
    <li class="l3"><a href="#s-13-8">13.8 Resources and prompts</a></li>
    <li class="l3"><a href="#s-13-9">13.9 Host-agent operating rules</a></li>
    <li class="l2"><a href="#ch-14">14 Development trace: making factor evolution traceable</a></li>
    <li class="l3"><a href="#s-14-1">14.1 Why a trace, and what it is not</a></li>
    <li class="l3"><a href="#s-14-2">14.2 What is recorded along the path</a></li>
    <li class="l3"><a href="#s-14-3">14.3 Trace model</a></li>
    <li class="l3"><a href="#s-14-4">14.4 Iteration history</a></li>
    <li class="l3"><a href="#s-14-5">14.5 Completeness rule and exports</a></li>
    <li class="l3"><a href="#s-14-6">14.6 Limits and sizing</a></li>
    <li class="l2"><a href="#ch-15">15 Logging: record everything, readable through MCP</a></li>
    <li class="l3"><a href="#s-15-1">15.1 Principles</a></li>
    <li class="l3"><a href="#s-15-2">15.2 Mandatory fields and correlation ids</a></li>
    <li class="l3"><a href="#s-15-3">15.3 What is logged</a></li>
    <li class="l3"><a href="#s-15-4">15.4 Storage and retention</a></li>
    <li class="l3"><a href="#s-15-5">15.5 Reading logs through MCP and the CLI</a></li>
    <li class="l3"><a href="#s-15-6">15.6 Redaction and what logs never contain</a></li>
    <li class="l2"><a href="#ch-16">16 Data model and APIs</a></li>
    <li class="l3"><a href="#s-16-1">16.1 registry_db</a></li>
    <li class="l3"><a href="#s-16-2">16.2 research_db (blackboard, jobs and trace)</a></li>
    <li class="l3"><a href="#s-16-3">16.3 eval_db</a></li>
    <li class="l3"><a href="#s-16-4">16.4 control_db</a></li>
    <li class="l3"><a href="#s-16-5">16.5 Registry API (registry-api)</a></li>
    <li class="l3"><a href="#s-16-6">16.6 Feedback API (feedback-api, GET only)</a></li>
    <li class="l3"><a href="#s-16-7">16.7 Research control API (research-api, called only by qfr-mcp)</a></li>
    <li class="l3"><a href="#s-16-8">16.8 Eval admin API (eval-admin-api, called only by qfr-mcp)</a></li>
    <li class="l3"><a href="#s-16-9">16.9 Authentication</a></li>
    <li class="l2"><a href="#ch-17">17 Security, operations and deployment on the Mac Studio</a></li>
    <li class="l3"><a href="#s-17-1">17.1 Threat model</a></li>
    <li class="l3"><a href="#s-17-2">17.2 Deployment target and Docker Compose topology</a></li>
    <li class="l3"><a href="#s-17-3">17.3 Installation and setup</a></li>
    <li class="l3"><a href="#s-17-4">17.4 Operations runbook</a></li>
    <li class="l3"><a href="#s-17-5">17.5 Backups and recovery</a></li>
    <li class="l2"><a href="#ch-18">18 Testing strategy and benchmarks</a></li>
    <li class="l3"><a href="#s-18-1">18.1 Test layers</a></li>
    <li class="l3"><a href="#s-18-2">18.2 Named test suites</a></li>
    <li class="l3"><a href="#s-18-3">18.3 Benchmarks</a></li>
    <li class="l2"><a href="#ch-19">19 Implementation roadmap</a></li>
    <li class="l3"><a href="#s-19-1">19.1 Milestones</a></li>
    <li class="l2"><a href="#ch-20">20 Defaults</a></li>
    <li class="l2"><a href="#ch-21">21 Coding-agent kit</a></li>
    <li class="l3"><a href="#s-21-1">21.1 AGENTS.md</a></li>
    <li class="l3"><a href="#s-21-2">21.2 Phase kickoff prompt</a></li>
    <li class="l3"><a href="#s-21-3">21.3 Host-agent guide (summary of docs/HOST_AGENT_GUIDE.md)</a></li>
    <li class="l3"><a href="#s-21-4">21.4 Global definition of done</a></li>
    <li class="l2"><a href="#ch-22">22 Risks and mitigations</a></li>
    <li class="l2"><a href="#ch-23">23 Glossary and references</a></li>
    <li class="l3"><a href="#s-23-1">23.1 Glossary</a></li>
    <li class="l3"><a href="#s-23-2">23.2 References</a></li>
  </ol>
  <p class="toc-empty">No matching sections.</p>
</nav>

<main id="main">
<!-- ===================================================== CHAPTER 0 -->
<section class="chapter" id="ch-0">
<div class="chapter-kicker"><span class="n">0</span>Chapter 0</div>
<h2>How to use this plan<a class="anchor" href="#ch-0">#</a></h2>
<p class="lead">This document is the single source of truth for building QFR. The coding agent builds from this document alone, one phase at a time. Throughout, "v1" means the first release of QFR, which Phases 0 to 7 deliver.</p>
<ol>
  <li><strong>Create an empty repository.</strong> Before anything else, copy the <code>AGENTS.md</code> block from <a href="#s-21-1">Section 21.1</a> into the repository root and save this document as <code>docs/PLAN.md</code>. <code>AGENTS.md</code> holds the non-negotiable rules the coding agent follows in every session.</li>
  <li><strong>Give the coding agent one phase at a time</strong> from <a href="#ch-19">Section 19</a>, using the kickoff prompt in <a href="#s-21-2">Section 21.2</a>. Each phase lists tasks with IDs (for example P4.11), deliverables and acceptance checks. A phase is done only when every acceptance check passes in CI and, where the check says so, on the Mac Studio.</li>
  <li><strong>Whenever a value is needed</strong> (window dates, thresholds, quotas, budgets, ports, retention periods), use the default in <a href="#ch-20">Section 20</a>. Every default <span class="kw">MUST</span> live in a config file and never appear as a magic number in code.</li>
  <li><strong>Keywords.</strong> <span class="badge must">MUST</span> / <span class="badge must">MUST NOT</span> are hard requirements enforced by tests. <span class="badge should">SHOULD</span> is a strong default, and any deviation is recorded in <code>docs/decisions.md</code>. <span class="badge may">MAY</span> is optional.</li>
  <li><strong>Gaps and contradictions.</strong> If the coding agent finds one, it records the issue and its chosen resolution in <code>docs/decisions.md</code> and continues. It <span class="kw">MUST NOT</span> weaken a design invariant (<a href="#ch-3">Section 3</a>) to make something work. When in doubt, it picks the option that better protects measurement integrity and traceability.</li>
  <li><strong>No over-engineering.</strong> The plan names exactly one technology per concern. Anything not named here (message brokers, log stacks, web dashboards, orchestration frameworks, model routers) is out of scope unless a later phase adds it explicitly.</li>
</ol>


<div class="table-wrap">
<table>
<thead><tr><th>Section</th><th>What it defines</th><th>Used in phases</th></tr></thead>
<tbody>
<tr><td><a href="#ch-3">3. Design invariants</a></td><td>Rules every component must respect, each with the test that proves it</td><td>All</td></tr>
<tr><td><a href="#ch-4">4. Architecture</a></td><td>Components, trust zones, the owner workflow, key decisions</td><td>All</td></tr>
<tr><td><a href="#ch-5">5. Stack and repository</a></td><td>Languages, libraries, services, layout, credentials</td><td>0</td></tr>
<tr><td><a href="#ch-6">6. Market data</a></td><td>Sources, data zones, windows, timing conventions, synthetic worlds</td><td>1</td></tr>
<tr><td><a href="#ch-7">7. DSL and artifacts</a></td><td>Factor language, operators, factor and strategy manifests, lifecycle</td><td>1, 2, 6</td></tr>
<tr><td><a href="#ch-8">8. Evaluation</a></td><td>Intake, screening, metrics, backtests, statistics, gates</td><td>3, 6</td></tr>
<tr><td><a href="#ch-9">9. Release policy</a></td><td>What feedback is released to research, how coarse, how often</td><td>3, 6</td></tr>
<tr><td><a href="#ch-10">10. Acceptance and pools</a></td><td>Holdout, simulated trading, pools, promotion, monitoring, epochs</td><td>6, 8</td></tr>
<tr><td><a href="#ch-11">11. Research system</a></td><td>Agents, tools, permissions, outputs, generation workflow, LLM providers</td><td>4</td></tr>
<tr><td><a href="#ch-12">12. Evolution</a></td><td>Islands, archive, fitness, selection, operators, bandit</td><td>5</td></tr>
<tr><td><a href="#ch-13">13. MCP front door</a></td><td>Tools, resources, prompts, jobs, deliverables, approvals, setup</td><td>0, 2, 4, 6, 7</td></tr>
<tr><td><a href="#ch-14">14. Development trace</a></td><td>What is recorded about each factor's development and how it is exported</td><td>4, 5, 7</td></tr>
<tr><td><a href="#ch-15">15. Logging</a></td><td>Mandatory fields, correlation ids, storage, reading logs through MCP</td><td>0, All</td></tr>
<tr><td><a href="#ch-16">16. Data model and APIs</a></td><td>Tables and endpoints for all services</td><td>2 to 7</td></tr>
<tr><td><a href="#ch-17">17. Security and deployment</a></td><td>Threat model, Mac Studio Compose topology, installation, runbook, backups</td><td>0, 7, 8</td></tr>
<tr><td><a href="#ch-18">18. Testing</a></td><td>Test suites, invariant tests, benchmarks</td><td>All</td></tr>
<tr><td><a href="#ch-19">19. Roadmap</a></td><td>Phases, tasks, acceptance checks, milestones</td><td>All</td></tr>
<tr><td><a href="#ch-20">20. Defaults</a></td><td>Every tunable value in one place</td><td>All</td></tr>
<tr><td><a href="#ch-21">21. Coding-agent kit</a></td><td>AGENTS.md, kickoff prompt, host-agent guide, definition of done</td><td>All</td></tr>
<tr><td><a href="#ch-22">22 and 23</a></td><td>Risks, glossary, references</td><td>Reference</td></tr>
</tbody>
</table>
</div>
</section>

<!-- ===================================================== CHAPTER 1 -->
<section class="chapter" id="ch-1">
<div class="chapter-kicker"><span class="n">1</span>Chapter 1</div>
<h2>Executive summary<a class="anchor" href="#ch-1">#</a></h2>
<p class="lead">QFR is a closed-loop research system. LLM agents propose quantitative equity factors and strategies. An independent, deterministic evaluation service measures them under its own controls. The agents learn only from the feedback the evaluator chooses to release. The owner steers everything through one door, approves what gets kept, and can always see how a result came to be.</p>

<h3 id="s-1-1"><span class="sn">1.1</span>What the owner experiences</h3>
<p>The owner never operates QFR directly. They talk to a <strong>host agent</strong> (Codex, Claude Code or any other MCP-capable agent) in their own harness. The host agent connects to QFR's <strong>MCP front door</strong>, turns the owner's intent into a structured research brief, submits it, follows progress, fetches the deliverable, explains it, and records the owner's approval. A typical exchange:</p>
<ol>
  <li>The owner writes, for example: "create a momentum-style strategy", or "based on the moving-average factors in the pool, improve the factors and design a new strategy", or "based on the attachment, review the methodology, factors and strategies, and use QFR to iterate them".</li>
  <li>The host agent reads the public protocol and policy cards and the pools over MCP, breaks the request into QFR-understandable inputs (a research brief with mode, seeds, constraints, deliverable criteria and budget) and submits it as a job.</li>
  <li>QFR runs research generations and independent evaluation on its own schedule. When a result meets the job's deliverable criteria it is published to the host agent through MCP.</li>
  <li>The host agent receives the deliverable: the artifact, its <strong>iteration history</strong> (how it developed from the original seed or hypothesis to the delivered version) and its <strong>backtesting results</strong>, and reports to the owner with the mandatory caveats.</li>
  <li>The owner approves. The host agent records the approval and saves factors to the <strong>factor pool</strong> and strategies to the <strong>strategy pool</strong>. Both pools are long-lived and start empty unless the owner imports a raw factor pool at setup.</li>
</ol>

<h3 id="s-1-2"><span class="sn">1.2</span>How the system is built</h3>
<p>The research side combines four patterns from the hybrid architecture:</p>
<ul>
  <li><strong>Supervisor–worker coordination.</strong> A supervisor plans each generation and allocates budget, and specialist agents (hypothesis researcher, factor engineer, critic, report analyst) work in parallel.</li>
  <li><strong>Shared research blackboard.</strong> A PostgreSQL store of jobs, hypotheses, candidates, reviews, population, lineage, interpretations, cached released reports and the development trace.</li>
  <li><strong>Evolutionary development.</strong> An island-based, quality-diversity population in the style of MAP-Elites, with LLM-guided and syntactic mutation and crossover, budgeted by a multi-armed bandit.</li>
  <li><strong>Standardized artifact preparation.</strong> A deterministic packager freezes approved candidates into immutable, content-hashed artifact versions with full provenance and a complete trace.</li>
</ul>
<p>The evaluation side is deterministic code with no LLM anywhere in the measurement path. It pulls published artifacts on its own schedule, applies its own protocols, run budget and quotas, writes immutable official records, and releases coarsened and rationed reports through a read-only Feedback API as soon as each one is recorded. The owner, through MCP, may read the full-precision official records; research agents never can.</p>

<h3 id="s-1-3"><span class="sn">1.3</span>Decisions that make the design robust</h3>
<ul>
  <li><strong>Physical data zones.</strong> Research processes only ever see data up to a research cutoff. All later windows exist only in the evaluation zone.</li>
  <li><strong>A four-window protocol.</strong> W1 gives coarsened feedback, W2 gives rationed pass/fail validation through a Ladder mechanism, W3 is a private holdout that is never released to research, and W4 is forward simulated trading after publication.</li>
  <li><strong>The release policy is an anti-overfitting mechanism</strong>, not a reporting convenience. Coarsening, per-family quotas, the Ladder and per-window burn meters come from adaptive data analysis research (the reusable holdout, the Ladder leaderboard). They limit how much each answer reveals and how many questions are asked; no finished result is held back, so research hears about every evaluation as soon as it is recorded.</li>
  <li><strong>Every evaluated version counts.</strong> A trial ledger feeds the Deflated Sharpe Ratio, the probability of backtest overfitting and burn accounting, so the cost of searching widely is priced in.</li>
  <li><strong>Forward incubation guards against LLM memorization.</strong> LLMs memorize historical market outcomes, so historical holdouts are contaminated. Only forward simulated trading after publication is clean evidence, and full acceptance requires it. The owner can still approve a deliverable at an earlier evidence tier, and the system always states which tier a result has reached.</li>
  <li><strong>Factors start as DSL expressions.</strong> A typed DSL with no access to dates or tickers and no way to look ahead removes arbitrary code execution from the MVP, makes mutation, crossover and deduplication trivial, and closes most evaluation-gaming channels. Python factors arrive later inside a sandbox.</li>
  <li><strong>Traceable development.</strong> Every step that turns a brief into a published version is recorded with its actor, inputs, full prompts and responses, deterministic checks and outcomes. A deliverable's iteration history is generated from this record, never written by an LLM.</li>
  <li><strong>Log everything, read it through MCP.</strong> Structured JSON logs with correlation ids from every service land in one logs volume. The host agent can search, tail and correlate them.</li>
  <li><strong>Three online providers, one adapter interface.</strong> Kimi, GLM and DeepSeek are reached through their OpenAI-compatible chat completions endpoints, with a profile per provider for thinking control, reasoning pass-back, tool choice and rate limits, per-role model configuration, cross-provider review and fallback chains. No local models.</li>
  <li><strong>Single host, real boundaries.</strong> Docker Compose on an Apple silicon Mac Studio, with separate networks, databases, roles and credentials per zone, and only loopback ports published.</li>
</ul>
<p>The default market for v1 is China A-shares: daily bars, a point-in-time CSI 300 universe, taken from the free, daily-updated community Qlib-format dataset (chenditc/investment_data). The system reads this format directly and does not depend on the qlib package. A synthetic market generator with planted alphas and a null world is mandatory for testing.</p>
</section>

<!-- ===================================================== CHAPTER 2 -->
<section class="chapter" id="ch-2">
<div class="chapter-kicker"><span class="n">2</span>Chapter 2</div>
<h2>Goals, non-goals and success criteria<a class="anchor" href="#ch-2">#</a></h2>

<h3 id="s-2-1"><span class="sn">2.1</span>Goals</h3>
<ul>
  <li><strong>G1.</strong> Automate the loop <em>brief → propose → publish → independently evaluate → release → learn → deliver</em> for cross-sectional daily equity factors and simple strategies built from them.</li>
  <li><strong>G2.</strong> Enforce the separation of proposal and measurement technically, not by convention.</li>
  <li><strong>G3.</strong> Make every result reproducible and traceable to an exact artifact version, protocol version, data snapshot and evaluator code version.</li>
  <li><strong>G4.</strong> Evolve a diverse population of factors under explicit LLM-cost and evaluation budgets.</li>
  <li><strong>G5.</strong> Promote only what the owner approves, after the system has shown the evidence tier reached (W1, W2, holdout, forward incubation), the multiple-testing-aware statistics and the caveats.</li>
  <li><strong>G6.</strong> Give the owner one control surface: a standard MCP server that a host agent drives. Through it the owner submits briefs, follows jobs, receives deliverables, reads evidence, approves, curates the pools and reads the logs.</li>
  <li><strong>G7.</strong> Record the development of every factor and strategy step by step, so that the path from the original idea to the delivered version can be inspected and exported without trusting an LLM's own account of it.</li>
  <li><strong>G8.</strong> Log every action inside the system with correlation ids, and make the logs readable through MCP.</li>
  <li><strong>G9.</strong> Run as a Docker Compose bundle on an Apple silicon Mac Studio with no external infrastructure.</li>
</ul>

<h3 id="s-2-2"><span class="sn">2.2</span>Non-goals for v1</h3>
<ul>
  <li>Real-money trading or any broker connectivity. Only forward simulation is in scope.</li>
  <li>Intraday, tick or order-book data. Alternative and text data.</li>
  <li>LLM-based judgement anywhere in official measurement.</li>
  <li>Fully automatic promotion. Nothing enters a pool without a recorded owner approval.</li>
  <li>Portfolio optimization with risk models. v1 strategies are factor combinations run through simple reference portfolio rules.</li>
  <li>A web dashboard or any human UI other than the host agent's own interface. The MCP front door is the product surface.</li>
  <li>Multi-user, multi-tenant or remote-access concerns. One owner, one machine, loopback only.</li>
  <li>Local or self-hosted LLMs. The research side uses the three named online providers.</li>
  <li>Default factor libraries, demo strategies, pilot fixtures or reference samples of any kind.</li>
</ul>

<h3 id="s-2-3"><span class="sn">2.3</span>Success criteria for v1</h3>
<p>These are measured by the benchmarks in <a href="#s-18-3">Section 18.3</a> and the end-to-end checks in <a href="#ch-19">Section 19</a>.</p>
<div class="table-wrap">
<table>
<thead><tr><th class="id">ID</th><th>Criterion</th><th>Target</th></tr></thead>
<tbody>
<tr><td class="id">SC1</td><td>Planted-alpha recovery on the synthetic world</td><td>A factor whose mean cross-sectional rank correlation with a planted alpha is at least 0.7 gets accepted within 10 generations under the scripted LLM</td></tr>
<tr><td class="id">SC2</td><td>Null-world safety</td><td>Zero accepted factors after 50 generations of scripted search that publish at least 500 versions</td></tr>
<tr><td class="id">SC3</td><td>Boundary integrity</td><td>All boundary tests (BND series) pass in CI</td></tr>
<tr><td class="id">SC4</td><td>Reproducibility</td><td>Re-running any official evaluation reproduces an identical results hash</td></tr>
<tr><td class="id">SC5</td><td>Feedback latency</td><td>A report is visible to research within 5 seconds of the evaluator recording its decision (median). For a version not deferred by quota, the median time from publication to its first released W1 report is the evaluation time plus at most one scheduler poll (60 seconds)</td></tr>
<tr><td class="id">SC6</td><td>Cost control</td><td>No generation exceeds its LLM cost cap, no job exceeds its job cap, and the daily cap acts as a hard stop</td></tr>
<tr><td class="id">SC7</td><td>Real-data smoke run</td><td>On CN data, 20 generations run unattended without a crash, and every report is linked to the exact version it evaluated</td></tr>
<tr><td class="id">SC8</td><td>Owner workflow</td><td>A real host agent (Claude Code or Codex) completes the five-step workflow on the synthetic world end to end: brief in, deliverable out with iteration history and backtest results, approval recorded, pool entry written</td></tr>
<tr><td class="id">SC9</td><td>Trace completeness</td><td>For every published version, the trace export reconstructs every hop from brief to publication, including the full prompt and response of every LLM step (TRC series)</td></tr>
<tr><td class="id">SC10</td><td>Log correlation</td><td>For any job id or version id, one MCP call returns the ordered log lines from every service that touched it (LOG-03)</td></tr>
<tr><td class="id">SC11</td><td>Empty start</td><td>A fresh deployment without a raw factor pool has zero factors, zero strategies and zero programs, and still completes a job from exploration alone (SET-01)</td></tr>
<tr><td class="id">SC12</td><td>Mac Studio deployment</td><td>The Compose bundle builds and runs natively on linux/arm64 on the Mac Studio, and the deployment check passes</td></tr>
</tbody>
</table>
</div>
</section>

<!-- ===================================================== CHAPTER 3 -->
<section class="chapter" id="ch-3">
<div class="chapter-kicker"><span class="n">3</span>Chapter 3</div>
<h2>Design invariants<a class="anchor" href="#ch-3">#</a></h2>
<p class="lead">Every invariant has an enforcement mechanism and test IDs from <a href="#s-18-2">Section 18.2</a>. The coding agent <span class="kw">MUST NOT</span> relax any of them.</p>
<div class="table-wrap">
<table>
<thead><tr><th class="id">ID</th><th>Invariant</th><th>Enforcement</th><th>Tests</th></tr></thead>
<tbody>
<tr><td class="id">INV-1</td><td><strong>Separation of proposal and measurement.</strong> Research code cannot invoke, configure, prioritize, pause or cancel evaluation, and cannot operate simulated accounts</td><td>No such endpoint or agent tool exists. Research services hold no evaluation credentials. import-linter forbids imports between qfr_research and qfr_eval</td><td>BND-01 to BND-05</td></tr>
<tr><td class="id">INV-2</td><td><strong>Immutability.</strong> A published artifact version never changes, and any change produces a new version</td><td>No UPDATE or DELETE grants. Database triggers raise on UPDATE and DELETE. The Registry API exposes no mutation route other than publish and append-only pool events</td><td>REG-01 to REG-04</td></tr>
<tr><td class="id">INV-3</td><td><strong>Pull-only intake.</strong> Only the evaluator decides what to pull, which checks to run and when</td><td>The registry has no push or notify path to the evaluator. Intake polls by sequence cursor. Pool changes are also pulled</td><td>EVL-01</td></tr>
<tr><td class="id">INV-4</td><td><strong>Read-only feedback.</strong> Research reads only released reports</td><td>The Feedback API exposes GET routes only and serves only released reports</td><td>BND-03</td></tr>
<tr><td class="id">INV-5</td><td><strong>Version-linked evidence.</strong> Each official record and released report references one artifact version id plus its content hash, protocol version, data snapshot id and evaluator code version</td><td>NOT NULL foreign keys and schema validation</td><td>EVL-02</td></tr>
<tr><td class="id">INV-6</td><td><strong>Holdout isolation.</strong> W3 numbers never reach research. Only the acceptance decision and a reason category are released. The owner may read them through MCP, labelled owner-only</td><td>The release engine has no mapping for W3 metrics. A scan test checks every released report. Owner-grade reads go through the eval admin API only</td><td>REL-05</td></tr>
<tr><td class="id">INV-7</td><td><strong>Every evaluated version counts.</strong> Each version evaluated on a window is a trial, failures included</td><td>The trial-ledger row is written in the same transaction as the official record</td><td>EVL-06</td></tr>
<tr><td class="id">INV-8</td><td><strong>Deterministic measurement.</strong> Evaluation has no LLM, no network and no wall-clock dependence, and uses fixed seeds</td><td>Evaluation workers hold no LLM keys and have no network egress. Re-runs compare results hashes</td><td>EVL-04</td></tr>
<tr><td class="id">INV-9</td><td><strong>Physical data zones.</strong> Research processes can read only data dated on or before the research cutoff</td><td>Research containers mount only the research-zone snapshot, which the zone builder truncates by date</td><td>BND-06</td></tr>
<tr><td class="id">INV-10</td><td><strong>Attribution and audit.</strong> Every write records the principal, a timestamp and a request id in an append-only event log, and every MCP call is audited</td><td>The repository layer writes events, audit tables are insert-only, and the MCP server writes an audit row per call</td><td>AUD-01, MCP-01</td></tr>
<tr><td class="id">INV-11</td><td><strong>Owner sign-off.</strong> Nothing enters a pool, and no acceptance case closes as accepted, without an approval record created from the owner's explicit confirmation through MCP. No code path promotes automatically</td><td>Pool writes and acceptance decisions require an approval id. The host agent must pass the owner's confirmation phrase. The research zone has no pool-write route</td><td>ACC-03, POOL-01</td></tr>
<tr><td class="id">INV-12</td><td><strong>Sanitized feedback.</strong> Diagnostics released to research are codes from a fixed vocabulary. No free text, stack traces, timings or values produced by executing artifact code are released</td><td>The release engine whitelists fields, and reason codes are an enum</td><td>REL-04</td></tr>
<tr><td class="id">INV-13</td><td><strong>Traceable development.</strong> Every published version has a complete, append-only development trace from brief to publication: actor, inputs, full prompts and responses, deterministic check results and outcomes. Publication is refused when the trace is incomplete</td><td>The packager verifies required trace steps before publishing. Trace tables are insert-only. Agent runs persist full request and response text</td><td>TRC-01 to TRC-03</td></tr>
<tr><td class="id">INV-14</td><td><strong>The host agent is not a research agent.</strong> The MCP front door exposes only owner-grade control: briefs, reads, approvals, pool curation, logs. It cannot run research tools, publish artifacts, write official records, alter runs or hold LLM keys</td><td>The MCP tool registry is snapshot-tested. The MCP service has no LLM credentials and no research_rw or eval_rw role; it calls the APIs with its own tokens</td><td>MCP-02, BND-07</td></tr>
</tbody>
</table>
</div>
</section>
<!-- ===================================================== CHAPTER 4 -->
<section class="chapter" id="ch-4">
<div class="chapter-kicker"><span class="n">4</span>Chapter 4</div>
<h2>Architecture<a class="anchor" href="#ch-4">#</a></h2>

<h3 id="s-4-1"><span class="sn">4.1</span>System overview</h3>
<p>QFR has four zones: a research zone of LLM agents, an immutable registry that also holds the owner's pools, an evaluation zone of deterministic code, and a <strong>control zone</strong>, which holds exactly one service: the MCP front door <code>qfr-mcp</code>. The owner's host agent talks to it, and it talks to the other zones through their APIs with its own credentials. Solid arrows show work, artifact or data flow. Dashed arrows show read-only flows.</p>

<figure id="fig-1">
<svg viewBox="0 0 1270 790" role="img" aria-labelledby="fig1-title">
<title id="fig1-title">Figure 1. System overview with control, research, registry, evaluation and logs zones</title>
<defs>
  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--d-edge)"/></marker>
  <marker id="arr-soft" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--d-edge-soft)"/></marker>
  <marker id="arr-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M10,0 L0,5 L10,10 z" fill="var(--d-edge)"/></marker>
</defs>

<!-- control zone -->
<rect class="zone control" x="20" y="16" width="1220" height="150"/>
<text class="zone-title zt control" x="36" y="40">Control zone · the owner's side · no LLM keys · no research or evaluation database roles</text>
<g class="node human"><rect x="40" y="70" width="170" height="74"/><text x="125" y="101" text-anchor="middle">Human owner</text><text class="sub" x="125" y="121" text-anchor="middle">intent · approval · curation</text></g>
<g class="node control"><rect x="240" y="70" width="220" height="74"/><text x="350" y="101" text-anchor="middle">Host agent</text><text class="sub" x="350" y="121" text-anchor="middle">Codex · Claude Code · any MCP client</text></g>
<g class="node control"><rect x="560" y="58" width="660" height="98"/><text x="890" y="88" text-anchor="middle">MCP front door · qfr-mcp</text><text class="sub" x="890" y="110" text-anchor="middle">tools, resources and prompts for jobs · deliverables · evidence · traces · pools · approvals · logs</text><text class="sub" x="890" y="132" text-anchor="middle">streamable HTTP on 127.0.0.1:8765 · bearer token · every call audited</text></g>
<path class="edge both" d="M210,107 H240"/>
<path class="edge both" d="M460,107 H560"/>
<text class="elabel" x="510" y="97" text-anchor="middle">MCP over HTTP</text>

<!-- research zone -->
<rect class="zone research" x="20" y="206" width="470" height="440"/>
<text class="zone-title zt research" x="36" y="228">Research zone · LLM agents · research-zone data only</text>
<g class="ext"><rect x="40" y="244" width="430" height="50"/><text x="255" y="264" text-anchor="middle">Online LLM providers · Kimi · GLM · DeepSeek</text><text class="sub" x="255" y="282" text-anchor="middle">OpenAI-compatible APIs · reached only by research-worker · keys never leave it</text></g>
<g class="node research"><rect x="40" y="318" width="210" height="56"/><text x="145" y="342" text-anchor="middle">Supervisor</text><text class="sub" x="145" y="360" text-anchor="middle">plans generations · allocates budget</text></g>
<g class="node research"><rect x="270" y="318" width="200" height="56"/><text x="370" y="342" text-anchor="middle">Specialists</text><text class="sub" x="370" y="360" text-anchor="middle">hypothesis · engineer · critic · analyst</text></g>
<g class="node research"><rect x="40" y="398" width="210" height="56"/><text x="145" y="422" text-anchor="middle">Evolution engine</text><text class="sub" x="145" y="440" text-anchor="middle">islands · archive · selection · bandit</text></g>
<g class="node research"><rect x="270" y="398" width="200" height="56"/><text x="370" y="422" text-anchor="middle">Packager</text><text class="sub" x="370" y="440" text-anchor="middle">trace check · freeze · publish</text></g>
<g class="node store"><rect x="40" y="478" width="210" height="64"/><text x="145" y="500" text-anchor="middle">Blackboard + trace</text><text class="sub" x="145" y="516" text-anchor="middle">research_db · jobs · hypotheses · candidates</text><text class="sub" x="145" y="530" text-anchor="middle">reviews · lineage · trace steps · agent runs</text></g>
<g class="node store"><rect x="270" y="478" width="200" height="64"/><text x="370" y="504" text-anchor="middle">Research-zone snapshot</text><text class="sub" x="370" y="522" text-anchor="middle">dates up to cutoff · read-only mount</text></g>
<g class="node research"><rect x="40" y="566" width="430" height="56"/><text x="255" y="590" text-anchor="middle">Deterministic research services</text><text class="sub" x="255" y="608" text-anchor="middle">feedback sync · job monitor · deliverable assembler · trace exporter</text></g>
<path class="edge" d="M145,318 V294"/>
<path class="edge" d="M370,318 V294"/>
<path class="edge both" d="M250,346 H270"/>
<path class="edge dashed" d="M145,398 V374"/>
<path class="edge" d="M370,374 V398"/>
<path class="edge both" d="M145,454 V478"/>
<path class="edge both" d="M30,346 H40 M30,346 V510 H40"/>
<path class="edge" d="M470,346 H482 V510 H470"/>
<text class="elabel" transform="translate(486,428) rotate(-90)" text-anchor="middle">workbench reads W0</text>
<path class="edge dashed" d="M145,542 V566"/>

<!-- registry zone -->
<rect class="zone registry" x="510" y="206" width="230" height="440"/>
<text class="zone-title zt registry" x="526" y="228">Registry and pools · shared</text>
<g class="node store"><rect x="530" y="318" width="190" height="70"/><text x="625" y="344" text-anchor="middle">Immutable artifact versions</text><text class="sub" x="625" y="361" text-anchor="middle">factor · strategy · research_note</text><text class="sub" x="625" y="376" text-anchor="middle">lineage · provenance · content hashes</text></g>
<g class="node store"><rect x="530" y="420" width="190" height="58"/><text x="625" y="444" text-anchor="middle">Factor pool</text><text class="sub" x="625" y="462" text-anchor="middle">owner-curated · append-only events</text></g>
<g class="node store"><rect x="530" y="500" width="190" height="58"/><text x="625" y="524" text-anchor="middle">Strategy pool</text><text class="sub" x="625" y="542" text-anchor="middle">owner-curated · append-only events</text></g>
<g class="node store"><rect x="530" y="580" width="190" height="44"/><text x="625" y="598" text-anchor="middle">registry_db</text><text class="sub" x="625" y="614" text-anchor="middle">versions by packager · pools by qfr-mcp</text></g>

<!-- evaluation zone -->
<rect class="zone eval" x="760" y="206" width="480" height="440"/>
<text class="zone-title zt eval" x="776" y="228">Evaluation zone · deterministic code · no LLM</text>
<g class="node store"><rect x="780" y="244" width="440" height="50"/><text x="1000" y="264" text-anchor="middle">Full snapshot · all windows · read-only mount</text><text class="sub" x="1000" y="282" text-anchor="middle">rebuilt daily by data-ingest · old snapshots retained for reproducibility</text></g>
<g class="node eval"><rect x="780" y="318" width="215" height="56"/><text x="887" y="342" text-anchor="middle">Intake and scheduler</text><text class="sub" x="887" y="360" text-anchor="middle">eligibility · dedup · quotas · pool sync</text></g>
<g class="node eval"><rect x="1015" y="318" width="205" height="56"/><text x="1117" y="342" text-anchor="middle">Screening</text><text class="sub" x="1117" y="360" text-anchor="middle">static checks · lookahead probe</text></g>
<g class="node eval"><rect x="780" y="398" width="215" height="56"/><text x="887" y="422" text-anchor="middle">Backtests W1 · W2 · W3</text><text class="sub" x="887" y="440" text-anchor="middle">official metrics · gates · statistics</text></g>
<g class="node eval"><rect x="1015" y="398" width="205" height="56"/><text x="1117" y="422" text-anchor="middle">Simulated trading W4</text><text class="sub" x="1117" y="440" text-anchor="middle">forward incubation · replay mode</text></g>
<g class="node store"><rect x="780" y="478" width="215" height="64"/><text x="887" y="502" text-anchor="middle">Official records + trial ledger</text><text class="sub" x="887" y="520" text-anchor="middle">eval_db · full precision · insert-only</text></g>
<g class="node feedback"><rect x="1015" y="478" width="205" height="56"/><text x="1117" y="502" text-anchor="middle">Release engine</text><text class="sub" x="1117" y="520" text-anchor="middle">policy · coarsening · whitelist · Ladder</text></g>
<g class="node eval"><rect x="780" y="566" width="215" height="56"/><text x="887" y="590" text-anchor="middle">Acceptance and library</text><text class="sub" x="887" y="608" text-anchor="middle">gates · cases · monitoring · alerts</text></g>
<g class="node feedback"><rect x="1015" y="566" width="205" height="56"/><text x="1117" y="590" text-anchor="middle">Feedback API · GET only</text><text class="sub" x="1117" y="608" text-anchor="middle">released reports · public cards · library</text></g>
<path class="edge" d="M995,346 H1015"/>
<path class="edge" d="M1040,374 L975,398"/>
<path class="edge" d="M960,374 L1040,398"/>
<path class="edge" d="M887,454 V478"/>
<path class="edge" d="M1060,454 L995,492"/>
<path class="edge" d="M995,510 H1015"/>
<path class="edge" d="M1117,534 V566"/>
<path class="edge" d="M887,542 V566"/>

<!-- cross-zone edges -->
<path class="edge" d="M640,156 L330,206"/>
<text class="elabel strong" x="322" y="181" text-anchor="end">research control API</text>
<text class="elabel" x="322" y="195" text-anchor="end">jobs · charters · traces · deliverables</text>
<path class="edge" d="M660,156 L625,206"/>
<text class="elabel strong" x="650" y="196" text-anchor="start">pool writes with approval id</text>
<path class="edge" d="M1000,156 V206"/>
<text class="elabel strong" x="1010" y="181" text-anchor="start">eval admin API</text>
<text class="elabel" x="1010" y="195" text-anchor="start">owner-grade reads · config · decisions</text>
<path class="edge" d="M470,426 L530,372"/>
<text class="elabel strong" x="538" y="404" text-anchor="start">publish</text>
<path class="edge" d="M720,353 H780"/>
<text class="elabel strong" x="750" y="344" text-anchor="middle">pull since_seq</text>
<path class="edge" d="M720,449 L780,372"/>
<text class="elabel" x="770" y="420" text-anchor="middle">pool sync (pull)</text>
<path class="edge dashed" d="M530,449 H490"/>
<text class="elabel" x="510" y="470" text-anchor="middle">read pools</text>
<path class="edge dashed" d="M1117,622 V664 H255 V622"/>
<text class="elabel" x="690" y="659" text-anchor="middle">released reports only · GET · coarsened, rationed</text>
<path class="edge dashed" d="M1220,107 H1252 V726 H1242"/>
<text class="elabel" transform="translate(1262,420) rotate(-90)" text-anchor="middle">qfr-mcp reads the logs volume</text>

<!-- logs band -->
<rect class="zone logs" x="20" y="684" width="1220" height="84"/>
<text class="zone-title zt logs" x="36" y="708">Logs volume · one JSON-lines file per service per day · correlation ids on every line</text>
<text class="elabel" x="36" y="730">written by every service in every zone · read-only to qfr-mcp (logs.search · logs.tail · logs.correlate) · rotated and retained by policy</text>
<text class="elabel" x="36" y="750">secrets scrubbed at the sink · research containers never mount evaluation logs · audit events also live in each database</text>
<path class="edge" d="M120,646 V684"/>
<path class="edge" d="M1180,646 V684"/>
</svg>
<figcaption><b>Figure 1. System overview.</b> The owner acts through a host agent, which drives the MCP front door. The front door reaches the research zone through the research control API, the registry through its pool routes, and the evaluation zone through the eval admin API. Research agents call the online providers; nothing else does. Evaluation pulls versions and pool changes from the registry on its own schedule and answers research only through the GET-only Feedback API. Every service writes to the logs volume, which the front door can read.</figcaption>
<details class="src"><summary>Diagram source (Mermaid)</summary>
<pre><code>flowchart TB
  subgraph CZ["Control zone"]
    OWN["Human owner"] &lt;--&gt; HOST["Host agent (Codex / Claude Code / other)"]
    HOST &lt;--&gt;|"MCP over loopback HTTP"| MCP["MCP front door qfr-mcp"]
  end
  subgraph RZ["Research zone: LLM agents, research-zone data only"]
    LLM["Online providers: Kimi, GLM, DeepSeek"]
    SUP["Supervisor"] --&gt; LLM
    WRK["Specialists"] --&gt; LLM
    EVO["Evolution engine"] -.-&gt; SUP
    SUP &lt;--&gt; WRK --&gt; PKG["Packager"]
    BB[("Blackboard + trace, research_db")]
    RDATA[("Research-zone snapshot")]
    DET["Feedback sync, job monitor, deliverable assembler"]
  end
  subgraph REG["Registry and pools (registry_db)"]
    ART[("Immutable artifact versions")]
    FP[("Factor pool")]
    SP[("Strategy pool")]
  end
  subgraph EZ["Evaluation zone: deterministic code, no LLM"]
    EDATA[("Full snapshot")]
    INT["Intake and scheduler"] --&gt; SCR["Screening"] --&gt; BT["Backtests W1, W2, W3"]
    INT --&gt; SIM["Simulated trading W4"]
    BT --&gt; REC[("Official records + trial ledger")]
    SIM --&gt; REC --&gt; RLS["Release engine"] --&gt; FAPI["Feedback API, GET only"]
    REC --&gt; ACC["Acceptance and library"]
  end
  LOGS[("Logs volume")]
  MCP --&gt;|"research control API"| RZ
  MCP --&gt;|"pool writes with approval id"| FP
  MCP --&gt;|"eval admin API"| EZ
  PKG --&gt;|"publish"| ART
  ART --&gt;|"pull since_seq"| INT
  FP --&gt;|"pool sync (pull)"| INT
  FP -.-&gt;|"read"| WRK
  FAPI -.-&gt;|"released reports only"| DET
  RZ --&gt; LOGS
  REG --&gt; LOGS
  EZ --&gt; LOGS
  LOGS -.-&gt;|"read-only"| MCP</code></pre>
</details>
</figure>

<p>There are three distinct decisions, and they belong to different owners. <strong>Evolutionary selection</strong>, owned by the research zone, chooses the next research candidates. <strong>Measurement</strong>, owned by the evaluation zone, produces official records and decides what is released. <strong>Promotion</strong>, owned by the human owner through MCP, decides what enters the pools. Official records never enter the writable research blackboard; it stores only cached copies of released reports, links to them, and the agents' interpretations. The MCP front door composes owner-grade views at read time from all three zones and stores only its own approvals and audit.</p>

<h3 id="s-4-2"><span class="sn">4.2</span>Components and owners</h3>
<div class="table-wrap">
<table>
<thead><tr><th>Component</th><th>Zone</th><th>Responsibility</th><th>Implemented as</th><th>Phase</th></tr></thead>
<tbody>
<tr><td>MCP front door</td><td>Control</td><td>The owner's only control surface: tools, resources and prompts for setup, jobs, deliverables, evidence, traces, approvals, pool curation, operations and logs. Stateless except approvals and audit</td><td>Python MCP server <code>qfr-mcp</code> (official MCP SDK) plus <code>control_db</code></td><td>0, 2, 4, 6, 7</td></tr>
<tr><td>Host agent</td><td>Control (external)</td><td>Translates the owner's intent into briefs, follows jobs, explains deliverables, records approvals. Not part of this repository</td><td>Codex, Claude Code or any MCP client</td><td>n/a</td></tr>
<tr><td>Research control API</td><td>Research</td><td>Jobs, programs, charters, blackboard reads, traces, deliverables. Called only by qfr-mcp</td><td>FastAPI service <code>research-api</code></td><td>4</td></tr>
<tr><td>Research orchestrator</td><td>Research</td><td>Runs the job and generation state machines, agent calls and the research job queue</td><td>Python worker <code>research-worker</code></td><td>4</td></tr>
<tr><td>Supervisor</td><td>Research</td><td>Writes the generation plan. An LLM planner plus a deterministic validator and fallback</td><td>PydanticAI agent plus code</td><td>4</td></tr>
<tr><td>Specialists</td><td>Research</td><td>Hypothesis researcher, factor engineer, critic, report analyst, interpretation reviewer</td><td>PydanticAI agents on Kimi, GLM and DeepSeek</td><td>4</td></tr>
<tr><td>Provider layer</td><td>Research</td><td>OpenAI-compatible adapters, per-role model selection, fallback chains, price table, usage accounting</td><td>Thin module over PydanticAI's OpenAI-compatible model</td><td>4</td></tr>
<tr><td>Evolution engine</td><td>Research</td><td>Population, islands, archive, fitness, selection, variation operators, bandit</td><td>Deterministic Python module plus LLM mutation prompts</td><td>5</td></tr>
<tr><td>Workbench</td><td>Research</td><td>Computes factor statistics on the research-zone snapshot, using the evaluator's metric definitions</td><td>qfr_core library facade</td><td>1, 4</td></tr>
<tr><td>Packager</td><td>Research</td><td>Final validation, trace completeness check, manifest assembly, publication</td><td>Deterministic code</td><td>4</td></tr>
<tr><td>Job monitor and deliverable assembler</td><td>Research</td><td>Checks each job's deliverable criteria against released reports, assembles deliverables and iteration histories from the trace</td><td>Research job</td><td>4</td></tr>
<tr><td>Feedback sync</td><td>Research</td><td>Pulls released reports into the blackboard cache</td><td>Research job</td><td>4</td></tr>
<tr><td>Registry API</td><td>Shared</td><td>Publishes and serves immutable artifact versions; serves the pools and accepts append-only pool events from qfr-mcp</td><td>FastAPI service <code>registry-api</code> plus <code>registry_db</code></td><td>2</td></tr>
<tr><td>Data ingest</td><td>Evaluation</td><td>Downloads and validates data, builds full and research-zone snapshots</td><td>CLI and daily job <code>data-ingest</code></td><td>1, 3</td></tr>
<tr><td>Intake and scheduler</td><td>Evaluation</td><td>Polls the registry, checks eligibility, dedups, applies quotas, syncs the pool into the library, enqueues work fairly</td><td>Worker <code>eval-scheduler</code></td><td>3</td></tr>
<tr><td>Evaluation workers</td><td>Evaluation</td><td>Screening and W1, W2, W3 runs. Writes official records and the trial ledger</td><td>Worker <code>eval-worker</code>, N replicas</td><td>3, 6</td></tr>
<tr><td>Simulation engine</td><td>Evaluation</td><td>Daily forward incubation and replay mode</td><td>Worker <code>sim-engine</code></td><td>6</td></tr>
<tr><td>Release engine</td><td>Evaluation</td><td>Applies the release policy and writes released reports</td><td>Worker <code>release-worker</code></td><td>3</td></tr>
<tr><td>Feedback API</td><td>Evaluation edge</td><td>Read-only access to released reports and public cards</td><td>FastAPI service <code>feedback-api</code></td><td>3</td></tr>
<tr><td>Eval admin API</td><td>Evaluation</td><td>Protocols, policies, quotas, runs, owner-grade records, acceptance cases, library, alerts. Called only by qfr-mcp</td><td>FastAPI service <code>eval-admin-api</code></td><td>3, 6</td></tr>
<tr><td>Logs volume</td><td>All</td><td>JSON-lines files per service and day, rotated and retained by policy, read by qfr-mcp</td><td>Named Docker volume plus structlog sinks</td><td>0</td></tr>
</tbody>
</table>
</div>

<h3 id="s-4-3"><span class="sn">4.3</span>Trust boundaries</h3>
<div class="table-wrap">
<table>
<thead><tr><th>From</th><th>To</th><th>What crosses</th><th>Mechanism</th><th>Direction</th></tr></thead>
<tbody>
<tr><td>Owner</td><td>Host agent</td><td>Intent, questions, approvals in the owner's own words</td><td>The host agent's chat interface</td><td>Conversation</td></tr>
<tr><td>Host agent</td><td>MCP front door</td><td>Tool calls, resource reads, prompt reads</td><td>MCP over streamable HTTP on loopback with the owner's bearer token</td><td>Read and owner-grade write</td></tr>
<tr><td>MCP front door</td><td>Research zone</td><td>Jobs, charters, pause and resume, steering guidance; reads of blackboard, traces and deliverables</td><td>Research control API with the control token</td><td>Write briefs, read everything research-side</td></tr>
<tr><td>MCP front door</td><td>Registry</td><td>Pool entries and pool events carrying an approval id; reads of versions and pools</td><td>Registry API pool routes with the control token</td><td>Append-only write</td></tr>
<tr><td>MCP front door</td><td>Evaluation zone</td><td>Protocols, policies, quotas, epochs, acceptance decisions carrying an approval id; owner-grade reads of records, gate values, simulations, alerts</td><td>Eval admin API with the owner token</td><td>Write configuration, read everything</td></tr>
<tr><td>MCP front door</td><td>Logs volume</td><td>Log lines from every service</td><td>Read-only volume mount</td><td>Read</td></tr>
<tr><td>Research</td><td>Registry</td><td>New artifact versions (manifest plus payload)</td><td>POST /v1/artifacts with the publisher token</td><td>Write-once</td></tr>
<tr><td>Research</td><td>Registry</td><td>Artifacts, families, lineage, pools</td><td>GET routes with the reader token</td><td>Read</td></tr>
<tr><td>Evaluation</td><td>Registry</td><td>Versions and pool events published since the cursors</td><td>GET routes with the evaluator token</td><td>Read</td></tr>
<tr><td>Evaluation</td><td>Research</td><td>Released reports, public protocol card, public policy card, library membership</td><td>Feedback API GET routes with the research reader token</td><td>Read by research</td></tr>
<tr><td>Evaluation</td><td>Research</td><td>Research-zone data snapshot</td><td>Read-only volume produced by data ingest</td><td>One-way</td></tr>
<tr><td>Research</td><td>Evaluation</td><td>Nothing else: no job submission, priority hints, cancellations, configuration or simulation control</td><td>None</td><td>Forbidden</td></tr>
<tr><td>Research</td><td>Pools</td><td>Nothing: research never writes a pool</td><td>No route, no token</td><td>Forbidden</td></tr>
<tr><td>Host agent</td><td>Research tools, official records, runs</td><td>Nothing: the host agent cannot run research tools, publish, write records or touch runs</td><td>No such MCP tool; qfr-mcp holds no such role</td><td>Forbidden</td></tr>
</tbody>
</table>
</div>

<h3 id="s-4-4"><span class="sn">4.4</span>The owner workflow end to end</h3>
<p>The five steps the owner experiences map onto MCP tools, job states and zone boundaries as follows. The research loop never blocks on evaluation, and the owner never blocks on either: the host agent polls or long-polls, and the system delivers when criteria are met.</p>

<figure id="fig-2">
<svg viewBox="0 0 1240 890" role="img" aria-labelledby="fig2-title">
<title id="fig2-title">Figure 2. The owner workflow as a sequence across the owner, host agent, MCP front door, research zone, registry and evaluation zone</title>
<g class="actor"><rect x="5" y="20" width="170" height="44"/><text x="90" y="47" text-anchor="middle">Human owner</text></g>
<g class="actor"><rect x="205" y="20" width="170" height="44"/><text x="290" y="47" text-anchor="middle">Host agent</text></g>
<g class="actor"><rect x="415" y="20" width="170" height="44"/><text x="500" y="47" text-anchor="middle">MCP front door</text></g>
<g class="actor"><rect x="625" y="20" width="170" height="44"/><text x="710" y="47" text-anchor="middle">Research zone</text></g>
<g class="actor"><rect x="835" y="20" width="170" height="44"/><text x="920" y="47" text-anchor="middle">Registry + pools</text></g>
<g class="actor"><rect x="1045" y="20" width="170" height="44"/><text x="1130" y="47" text-anchor="middle">Evaluation zone</text></g>
<line class="lifeline" x1="90" y1="64" x2="90" y2="870"/>
<line class="lifeline" x1="290" y1="64" x2="290" y2="870"/>
<line class="lifeline" x1="500" y1="64" x2="500" y2="870"/>
<line class="lifeline" x1="710" y1="64" x2="710" y2="870"/>
<line class="lifeline" x1="920" y1="64" x2="920" y2="870"/>
<line class="lifeline" x1="1130" y1="64" x2="1130" y2="870"/>

<g class="step"><circle cx="34" cy="110" r="11"/><text x="34" y="114" text-anchor="middle">1</text></g>
<line class="msg" x1="90" y1="110" x2="290" y2="110"/><text class="mlabel" x="190" y="102" text-anchor="middle">intent in plain language</text>
<g class="step"><circle cx="34" cy="150" r="11"/><text x="34" y="154" text-anchor="middle">2</text></g>
<line class="msg" x1="290" y1="150" x2="500" y2="150"/><text class="mlabel" x="395" y="142" text-anchor="middle">read cards and pools · qfr.job.submit(brief)</text>
<line class="msg" x1="500" y1="190" x2="710" y2="190"/><text class="mlabel" x="605" y="182" text-anchor="middle">create program and charter · start job</text>
<path class="selfloop" d="M710,228 H752 V252 H718"/><text class="mlabel" x="760" y="244" text-anchor="start">generations: propose · develop · review · select</text>
<g class="step"><circle cx="34" cy="290" r="11"/><text x="34" y="294" text-anchor="middle">3</text></g>
<line class="msg" x1="710" y1="290" x2="920" y2="290"/><text class="mlabel" x="815" y="282" text-anchor="middle">publish immutable versions (quota-limited)</text>
<line class="msg" x1="1130" y1="330" x2="920" y2="330"/><text class="mlabel" x="1025" y="322" text-anchor="middle">pull since_seq, on its own schedule</text>
<path class="selfloop" d="M1130,368 H1172 V392 H1138"/><text class="mlabel" x="1124" y="384" text-anchor="end">screen · W1/W2 backtests · official records · trial ledger</text>
<line class="msg ret" x1="1130" y1="430" x2="710" y2="430"/><text class="mlabel" x="920" y="422" text-anchor="middle">released reports (Feedback API, GET only, coarsened, immediate)</text>
<path class="selfloop" d="M710,468 H752 V492 H718"/><text class="mlabel" x="760" y="484" text-anchor="start">job monitor: criteria met → assemble deliverable + iteration history</text>
<g class="step"><circle cx="34" cy="530" r="11"/><text x="34" y="534" text-anchor="middle">4</text></g>
<line class="msg" x1="290" y1="530" x2="500" y2="530"/><text class="mlabel" x="395" y="522" text-anchor="middle">qfr.job.wait · qfr.deliverable.get</text>
<line class="msg" x1="500" y1="568" x2="710" y2="568"/><text class="mlabel" x="605" y="560" text-anchor="middle">fetch deliverable (research control API)</text>
<line class="msg ret" x1="710" y1="598" x2="500" y2="598"/><text class="mlabel" x="605" y="590" text-anchor="middle">artifact · iteration history · released reports · trace ref</text>
<line class="msg" x1="500" y1="636" x2="1130" y2="636"/><text class="mlabel" x="815" y="628" text-anchor="middle">owner-grade evidence (eval admin API)</text>
<line class="msg ret" x1="1130" y1="666" x2="500" y2="666"/><text class="mlabel" x="815" y="658" text-anchor="middle">official records · gate values · NAV series, labelled owner-only</text>
<line class="msg ret" x1="500" y1="704" x2="290" y2="704"/><text class="mlabel" x="395" y="696" text-anchor="middle">deliverable with backtest results</text>
<line class="msg ret" x1="290" y1="740" x2="90" y2="740"/><text class="mlabel" x="190" y="732" text-anchor="middle">report with caveats</text>
<g class="step"><circle cx="34" cy="778" r="11"/><text x="34" y="782" text-anchor="middle">5</text></g>
<line class="msg" x1="90" y1="778" x2="290" y2="778"/><text class="mlabel" x="190" y="770" text-anchor="middle">approve (explicit confirmation)</text>
<line class="msg" x1="290" y1="814" x2="500" y2="814"/><text class="mlabel" x="395" y="806" text-anchor="middle">qfr.approval.record · qfr.pool.add</text>
<line class="msg" x1="500" y1="846" x2="920" y2="846"/><text class="mlabel" x="710" y="838" text-anchor="middle">pool entry + event carrying the approval id</text>
<line class="msg" x1="1130" y1="870" x2="920" y2="870"/><text class="mlabel" x="1025" y="862" text-anchor="middle">pull pool changes → library</text>
</svg>
<figcaption><b>Figure 2. The owner workflow.</b> Numbered badges mark the five steps the owner sees. Everything between them runs on QFR's own schedule. The host agent never talks to the research or evaluation zones directly, and research never learns the owner-grade numbers that flow back through the front door.</figcaption>
<details class="src"><summary>Diagram source (Mermaid)</summary>
<pre><code>sequenceDiagram
  autonumber
  participant OWN as Human owner
  participant HOST as Host agent
  participant MCP as MCP front door
  participant RZ as Research zone
  participant REG as Registry + pools
  participant EZ as Evaluation zone
  OWN-&gt;&gt;HOST: intent in plain language
  HOST-&gt;&gt;MCP: read cards and pools; qfr.job.submit(brief)
  MCP-&gt;&gt;RZ: create program and charter, start job
  RZ-&gt;&gt;RZ: generations: propose, develop, review, select
  RZ-&gt;&gt;REG: publish immutable versions (quota-limited)
  EZ-&gt;&gt;REG: pull since_seq on its own schedule
  EZ-&gt;&gt;EZ: screen, W1/W2 backtests, official records, trial ledger
  EZ--&gt;&gt;RZ: released reports (Feedback API, GET only)
  RZ-&gt;&gt;RZ: job monitor: criteria met, assemble deliverable
  HOST-&gt;&gt;MCP: qfr.job.wait / qfr.deliverable.get
  MCP-&gt;&gt;RZ: fetch deliverable
  RZ--&gt;&gt;MCP: artifact, iteration history, released reports
  MCP-&gt;&gt;EZ: owner-grade evidence (eval admin API)
  EZ--&gt;&gt;MCP: official records, gate values, NAV
  MCP--&gt;&gt;HOST: deliverable with backtest results
  HOST--&gt;&gt;OWN: report with caveats
  OWN-&gt;&gt;HOST: approve
  HOST-&gt;&gt;MCP: qfr.approval.record; qfr.pool.add
  MCP-&gt;&gt;REG: pool entry and event with approval id
  EZ-&gt;&gt;REG: pull pool changes into the library</code></pre>
</details>
</figure>

<div class="grid-2">
<div class="card"><span class="mini">Step 1 · Owner</span><h4>States the intent</h4><p>Plain language in the host harness. Attachments (methodology notes, factor lists, strategy descriptions) stay with the host agent, which extracts what QFR can use.</p></div>
<div class="card"><span class="mini">Step 2 · Host agent</span><h4>Breaks it down and submits</h4><p>Reads <code>qfr://cards/protocol</code>, <code>qfr://cards/policy</code> and the pools, validates any extracted expressions with <code>qfr.dsl.validate</code>, builds a <code>ResearchBrief</code> (<a href="#s-13-3">Section 13.3</a>) and calls <code>qfr.job.submit</code>. The response states the job id, the derived charter and a realistic timeline for the deliverable tier.</p></div>
<div class="card"><span class="mini">Step 3 · QFR</span><h4>Researches and evaluates</h4><p>Generations run on the research cadence. Published versions are pulled and measured by the evaluator. The job monitor compares each released report with the brief's deliverable criteria. A result that meets them becomes a deliverable and the job state becomes <code>DELIVERABLE_READY</code>.</p></div>
<div class="card"><span class="mini">Step 4 · Host agent</span><h4>Receives and reports</h4><p><code>qfr.deliverable.get</code> returns the artifact, the iteration history generated from the trace, the released reports, and the owner-grade backtest results from the evaluator with their evidence tier and caveats. The host agent reports to the owner using the <code>qfr.report_deliverable</code> prompt.</p></div>
<div class="card"><span class="mini">Step 5 · Owner</span><h4>Approves, and the pools grow</h4><p>The owner confirms in their own words. The host agent records the approval with <code>qfr.approval.record</code>, quoting the owner's confirmation, then calls <code>qfr.pool.add</code> for each factor or strategy. The evaluator pulls the pool change into its library, and research can now use the entry as a parent.</p></div>
<div class="card"><span class="mini">Any time</span><h4>Inspects and steers</h4><p><code>qfr.trace.get</code> shows how a version was developed. <code>qfr.logs.correlate</code> shows what every service did with it. <code>qfr.job.steer</code> adds owner guidance for the next generation. <code>qfr.job.pause</code> and <code>qfr.job.cancel</code> stop spending.</p></div>
</div>

<div class="callout warn"><span class="ico">!</span><div><b class="t">Expectation setting for the owner</b>
<p>Feedback to research agents is coarse and rationed, but never held back: every report is released as soon as the evaluator records it. The owner's timeline is therefore set by how long evaluation, quotas and incubation take. First W1 reports arrive within minutes of a publication, W2 confirmation follows the family W2 quota (one W2 run per family every 7 days), and forward incubation lasts 60 trading days. A job's deliverable tier (<a href="#s-13-4">Section 13.4</a>) decides how long the owner waits. The default tier, <code>w1_pass</code>, typically delivers within a day; <code>incubated</code> takes about a quarter. The host agent must state the tier reached in every report.</p></div></div>

<h3 id="s-4-5"><span class="sn">4.5</span>Key decisions</h3>
<div class="table-wrap">
<table>
<thead><tr><th class="id">ID</th><th>Decision</th><th>Choice</th><th>Rationale</th><th>Rejected alternatives</th></tr></thead>
<tbody>
<tr><td class="id">D1</td><td>Core language</td><td>Python 3.12</td><td>Numerical ecosystem and the best support in agent libraries and the MCP SDK</td><td>TypeScript, whose numerical stack is weak</td></tr>
<tr><td class="id">D2</td><td>Dataframes</td><td>Polars plus NumPy</td><td>Fast, deterministic grouped and rolling operations with low memory use, native arm64 wheels</td><td>pandas as the core (still allowed in tests)</td></tr>
<tr><td class="id">D3</td><td>Factor representation</td><td>Typed DSL first, sandboxed Python later</td><td>Safe, mutation-friendly, lookahead-safe and easy to dedup</td><td>Free-form Python from day one</td></tr>
<tr><td class="id">D4</td><td>Agent framework</td><td>PydanticAI for typed agents over OpenAI-compatible models, plus a deterministic Python state machine for control flow</td><td>Typed outputs, usage and cost limits, offline TestModel and FunctionModel for tests, one adapter for all three providers</td><td>A free-running LLM supervisor, heavy graph frameworks, provider-specific SDKs</td></tr>
<tr><td class="id">D5</td><td>Persistence</td><td>PostgreSQL 16 with four databases (research_db, registry_db, eval_db, control_db) and separate roles</td><td>Strong constraints, triggers and grants with a single technology</td><td>A different engine per store</td></tr>
<tr><td class="id">D6</td><td>Job queue</td><td>Postgres job tables using FOR UPDATE SKIP LOCKED, one queue per zone</td><td>No extra infrastructure, and transactional with the records</td><td>Redis or Celery, Temporal</td></tr>
<tr><td class="id">D7</td><td>Market data storage</td><td>Content-addressed Parquet snapshots on read-only mounts</td><td>Reproducible, and zones are separated at the filesystem level</td><td>Panels stored in the database</td></tr>
<tr><td class="id">D8</td><td>Default market</td><td>CN A-shares daily, CSI 300 point-in-time, from the investment_data Qlib-binary release</td><td>Free, updated daily (needed for forward simulation), includes delisted names</td><td>yfinance (survivorship bias), paid US data (cost)</td></tr>
<tr><td class="id">D9</td><td>Qlib usage</td><td>Read the Qlib binary format directly and do not depend on the qlib package</td><td>Avoids Python-version and dependency friction on arm64, and keeps full control</td><td>The qlib backtest engine</td></tr>
<tr><td class="id">D10</td><td>Measurement</td><td>Deterministic code only, with no LLM judgement in official records</td><td>Reproducible and cannot be gamed by prompting</td><td>LLM-scored evaluation</td></tr>
<tr><td class="id">D11</td><td>Feedback to research</td><td>Released as soon as recorded. Coarsened and quota-limited. Ladder for W2. Nothing released for W3</td><td>Limits what each answer reveals and how many questions are asked, which is what adaptive overfitting depends on; research learns from every result without delay</td><td>Full-precision feedback; holding finished results back for batch release times, which slows research without reducing what is revealed</td></tr>
<tr><td class="id">D12</td><td>Promotion</td><td>Automated gates plus evidence tiers, and an owner approval recorded through MCP for every pool entry</td><td>Accounts for multiple testing and LLM memorization while keeping the owner in control of what is kept</td><td>Acceptance on backtests alone; automatic promotion</td></tr>
<tr><td class="id">D13</td><td>Human control surface</td><td>A standard MCP server driven by a host agent. No web dashboard, no CLI for the owner beyond setup and operations</td><td>The owner already works in an agent harness; MCP is the standard, client-agnostic way to expose tools, resources and prompts to it</td><td>Next.js dashboard, Streamlit, a bespoke chat UI</td></tr>
<tr><td class="id">D14</td><td>Deployment</td><td>Docker Compose on a single Apple silicon Mac Studio, images built for linux/arm64 (and amd64 in CI), separate networks and credentials per zone, loopback-only ports</td><td>Simple, native performance on the target, and the boundaries are still real</td><td>Kubernetes, cloud hosting, running processes directly on macOS</td></tr>
<tr><td class="id">D15</td><td>Research LLM providers</td><td>Kimi (Moonshot), GLM (Zhipu) and DeepSeek online APIs through their OpenAI-compatible chat completions endpoints: one adapter interface, one profile per provider, configured per role with fallback chains</td><td>Owner's choice; three independent providers reduce style collapse and correlated outages; the engineer and its critic use different providers. The providers differ in thinking control, reasoning pass-back, tool choice and limits, which the profiles absorb (Section 11.8)</td><td>A single provider; local models; Anthropic or OpenAI APIs</td></tr>
<tr><td class="id">D16</td><td>Pools</td><td>Factor pool and strategy pool as append-only entries and events in registry_db, referencing immutable versions and approval ids</td><td>The owner can "modify the DB" through MCP while versions stay immutable and every change is attributable and reversible by a new event</td><td>Mutable rows; pools inside research_db; a separate pool service</td></tr>
<tr><td class="id">D17</td><td>Traceability</td><td>An append-only trace_steps table plus agent_runs with full prompts and responses, joined with registry lineage and evaluation records into a deterministic trace export and iteration history</td><td>Makes LLM-driven evolution inspectable without trusting the LLM's own narrative</td><td>LLM-written changelogs; prompt hashes only</td></tr>
<tr><td class="id">D18</td><td>Logging</td><td>structlog JSON to stdout and to per-service JSON-lines files on one shared volume, with mandatory correlation fields; the MCP server reads the files</td><td>Everything is recorded and readable with no log stack to operate</td><td>Loki or Elasticsearch stacks; OpenTelemetry collectors; Prometheus</td></tr>
</tbody>
</table>
</div>
</section>
<!-- ===================================================== CHAPTER 5 -->
<section class="chapter" id="ch-5">
<div class="chapter-kicker"><span class="n">5</span>Chapter 5</div>
<h2>Technology stack and repository layout<a class="anchor" href="#ch-5">#</a></h2>

<h3 id="s-5-1"><span class="sn">5.1</span>Stack</h3>
<p>One technology per concern. Everything listed ships native <code>linux/arm64</code> wheels or images, which is a hard requirement for the Mac Studio target.</p>
<div class="table-wrap">
<table>
<thead><tr><th>Concern</th><th>Choice</th></tr></thead>
<tbody>
<tr><td>Python toolchain</td><td>uv workspace, Python 3.12, a single committed <code>uv.lock</code></td></tr>
<tr><td>Numerics</td><td>polars 1.x, numpy, pyarrow, scipy</td></tr>
<tr><td>Validation and configuration</td><td>pydantic v2, pydantic-settings, PyYAML</td></tr>
<tr><td>DSL parsing</td><td>lark</td></tr>
<tr><td>LLM agents</td><td>pydantic-ai with its DeepSeekProvider, MoonshotAIProvider and ZaiProvider classes over OpenAI-compatible chat completions. Providers: Kimi (Moonshot), GLM (Zhipu), DeepSeek. Model ids, prices, endpoints and thinking settings are configuration (<a href="#s-11-8">Section 11.8</a>)</td></tr>
<tr><td>MCP front door</td><td>The official Python MCP SDK (<code>mcp</code>, FastMCP server API), streamable HTTP transport bound to loopback, bearer-token authentication</td></tr>
<tr><td>Web services</td><td>fastapi, uvicorn</td></tr>
<tr><td>Database</td><td>PostgreSQL 16, SQLAlchemy 2 (sync, psycopg 3), Alembic with one environment per database</td></tr>
<tr><td>CLI</td><td>typer (<code>qfr</code> command: setup, doctor, data, eval, llm, logs, trace, backup)</td></tr>
<tr><td>Logging</td><td>structlog (JSON) with a stdlib bridge, file and stdout sinks, size-aware daily rotation. No OpenTelemetry, no Prometheus, no log stack in v1</td></tr>
<tr><td>Quality</td><td>pytest, hypothesis, pytest-xdist, import-linter, ruff, mypy (strict for qfr_core and qfr_mcp)</td></tr>
<tr><td>Containers</td><td>Docker Desktop for Mac (OrbStack is an acceptable drop-in), Docker Compose v2, multi-stage multi-arch Dockerfile (linux/arm64 primary, linux/amd64 for CI)</td></tr>
</tbody>
</table>
</div>

<h3 id="s-5-2"><span class="sn">5.2</span>Repository layout</h3>
<pre><code>qfr/
  AGENTS.md
  pyproject.toml                  uv workspace root
  uv.lock
  justfile                        check, test, build, up, down, setup, doctor, logs, mcp-config, backup, bench
  .importlinter                   boundary contracts
  configs/
    protocols/cn_csi300_daily_v1.yaml
    release_policies/default_v1.yaml
    quotas/default_v1.yaml
    research/charter_default.yaml
    research/providers.yaml       Kimi, GLM, DeepSeek endpoints, model ids, prices; keys referenced by env name only
    research/roles.yaml           role -&gt; provider/model, fallback chain, temperature, output mode, run limits
    epochs/epoch_001.yaml         window dates, mounted into evaluation containers only
    logging.yaml                  levels, sinks, rotation, retention, redaction patterns
    mcp.yaml                      bind address, port, limits, confirmation phrase template
  prompts/                        versioned prompt templates, research only
    supervisor.md hypothesis.md engineer.md critic.md analyst.md
    interpretation_review.md mutation.md crossover.md strategy.md
  packages/
    qfr_core/                     shared and deterministic: public schemas, DSL, operators,
                                  metrics, data readers, workbench facade, trace and log schemas
    qfr_registry/                 registry API, pools, database models
    qfr_research/                 agents, provider layer, tools, blackboard, jobs, workflow,
                                  evolution, packager, feedback sync, deliverables, research control API
    qfr_eval/                     ingest, intake, workers, protocols, backtest, simulation,
                                  release, feedback API, acceptance, admin API, private record schemas
    qfr_mcp/                      MCP server: tools, resources, prompts, approvals, audit, log reader
  infra/
    docker-compose.yml            the Mac Studio deployment
    docker-compose.ci.yml         CI overrides
    Dockerfile                    multi-stage, multi-arch
    postgres/init/                databases, roles, grants, triggers
    env.example                   every variable, no values
  imports/                        owner-provided files such as the raw factor pool; bind mount; gitignored
  exports/                        deliverable bundles, trace exports, log slices; bind mount; gitignored
  backups/                        nightly dumps; bind mount; gitignored
  data/                           gitignored: raw/, snapshots/full/&lt;id&gt;/, snapshots/research/&lt;id&gt;/
  tests/
    boundary/ e2e/ benchmarks/ mcp/
  docs/
    PLAN.md                       this document
    decisions.md                  decision log
    HOST_AGENT_GUIDE.md           how a host agent should drive QFR (Section 21.3)</code></pre>

<h3 id="s-5-3"><span class="sn">5.3</span>Code boundary contracts</h3>
<p>These are enforced with import-linter in CI (test BND-04).</p>
<ul>
  <li><code>qfr_research</code> <span class="kw">MUST NOT</span> import <code>qfr_eval</code>, and <code>qfr_eval</code> <span class="kw">MUST NOT</span> import <code>qfr_research</code>.</li>
  <li><code>qfr_registry</code> <span class="kw">MUST NOT</span> import <code>qfr_research</code> or <code>qfr_eval</code>.</li>
  <li><code>qfr_core</code> <span class="kw">MUST NOT</span> import any other qfr package.</li>
  <li><code>qfr_mcp</code> <span class="kw">MUST</span> import only <code>qfr_core</code>. It reaches every other component over HTTP with its own tokens, and it never opens a connection to research_db, registry_db or eval_db.</li>
  <li>Official-record schemas live in <code>qfr_eval</code>, not in <code>qfr_core</code>, so research code cannot construct them at all. Released-report schemas live in <code>qfr_core</code> because both sides need them. Owner-grade evidence returned by the eval admin API is validated in <code>qfr_mcp</code> against a JSON Schema that <code>qfr_eval</code> publishes at build time, so <code>qfr_mcp</code> never imports <code>qfr_eval</code>.</li>
  <li>Epoch and window definitions in <code>configs/epochs</code> are mounted only into evaluation containers. Research containers receive only the public protocol card through the Feedback API.</li>
  <li>Provider credentials exist only in the environment of <code>research-worker</code>. No other container, including <code>qfr-mcp</code>, receives them (test BND-07).</li>
</ul>

<h3 id="s-5-4"><span class="sn">5.4</span>Runtime topology</h3>
<p>In v1 a single PostgreSQL instance hosts four databases, and the separation comes from roles and credentials. Phase 8 may split research and evaluation into separate instances. The compose networks are listed in <a href="#s-17-2">Section 17.2</a>.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Service</th><th>Package</th><th>Database role</th><th>Can reach</th><th>Secrets</th><th>Mounts</th></tr></thead>
<tbody>
<tr><td>qfr-mcp</td><td>qfr_mcp</td><td>control_rw on control_db</td><td>research-api, registry-api, eval-admin-api, feedback-api; listens on 127.0.0.1:8765 of the Mac</td><td>MCP bearer token (owner), control tokens for the three APIs, feedback reader token</td><td>logs volume read-only; imports read-only; exports read-write</td></tr>
<tr><td>research-api</td><td>qfr_research</td><td>research_rw on research_db</td><td>postgres, registry-api, feedback-api</td><td>Research DB URL, research control token (to verify callers)</td><td>Research snapshot read-only; logs</td></tr>
<tr><td>research-worker</td><td>qfr_research</td><td>research_rw on research_db</td><td>postgres, registry-api, feedback-api, the three provider endpoints</td><td>Provider API keys, registry publisher token, feedback reader token</td><td>Research snapshot read-only; logs</td></tr>
<tr><td>registry-api</td><td>qfr_registry</td><td>registry_app on registry_db</td><td>postgres</td><td>Registry tokens (publisher, reader, evaluator, control)</td><td>logs</td></tr>
<tr><td>eval-scheduler</td><td>qfr_eval</td><td>eval_rw on eval_db</td><td>postgres, registry-api</td><td>Registry evaluator token</td><td>Full snapshot and epochs read-only; logs</td></tr>
<tr><td>eval-worker (N replicas)</td><td>qfr_eval</td><td>eval_rw on eval_db</td><td>postgres only, no egress</td><td>None</td><td>Full snapshot and epochs read-only; logs</td></tr>
<tr><td>release-worker</td><td>qfr_eval</td><td>eval_rw on eval_db</td><td>postgres</td><td>None</td><td>logs</td></tr>
<tr><td>sim-engine</td><td>qfr_eval</td><td>eval_rw on eval_db</td><td>postgres</td><td>None</td><td>Full snapshot read-only; logs</td></tr>
<tr><td>feedback-api</td><td>qfr_eval feedback module</td><td>feedback_ro on eval_db, SELECT on feedback views only</td><td>postgres</td><td>Feedback tokens</td><td>logs</td></tr>
<tr><td>eval-admin-api</td><td>qfr_eval</td><td>eval_rw on eval_db</td><td>postgres</td><td>Owner token (to verify qfr-mcp)</td><td>Epochs read-only; logs</td></tr>
<tr><td>data-ingest</td><td>qfr_eval ingest module</td><td>eval_rw on eval_db</td><td>Internet (data source only), postgres</td><td>None</td><td>Raw and snapshots read-write; logs</td></tr>
<tr><td>migrate (one-shot)</td><td>all packages</td><td>Per-database migration roles</td><td>postgres</td><td>Migration URLs</td><td>logs</td></tr>
</tbody>
</table>
</div>
<p>Database roles and grants:</p>
<ul>
  <li><code>registry_app</code>: INSERT and SELECT on registry tables, including pool entries and pool events. No UPDATE or DELETE. Triggers additionally block UPDATE and DELETE for every role on artifact and pool tables.</li>
  <li><code>research_rw</code>: full DML on research_db tables, except audit, trace and agent-run tables, which are INSERT and SELECT only. No CONNECT privilege on eval_db, registry_db or control_db.</li>
  <li><code>eval_rw</code>: DML on eval_db. official_records, trial_ledger, released_reports and audit tables are insert-only and protected by triggers. No CONNECT privilege on research_db or control_db.</li>
  <li><code>feedback_ro</code>: SELECT only on views in the feedback schema (released_reports_v, artifact_status_v, library_v, policy_card_v, protocol_card_v).</li>
  <li><code>control_rw</code>: INSERT and SELECT on control_db tables (approvals, mcp_calls, deliveries, setup_state are insert-only; setup_state uses new rows for changes). No CONNECT privilege on any other database.</li>
</ul>
<p>No evaluation container and no control container receives LLM API keys. Only <code>data-ingest</code> has internet egress on the evaluation side, and only <code>research-worker</code> has egress on the research side.</p>

<h3 id="s-5-5"><span class="sn">5.5</span>Configuration and environment variables</h3>
<p>Every variable is listed in <code>infra/env.example</code> without values. Secrets are supplied through the compose <code>.env</code> file with mode 0600 on the Mac and are never committed.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Variable</th><th>Used by</th><th>Purpose</th></tr></thead>
<tbody>
<tr><td>RESEARCH_DB_URL, REGISTRY_DB_URL, EVAL_DB_URL, FEEDBACK_DB_URL, CONTROL_DB_URL</td><td>Services in each zone</td><td>Role-specific connection strings</td></tr>
<tr><td>REGISTRY_API_URL, FEEDBACK_API_URL, RESEARCH_API_URL, EVAL_ADMIN_API_URL</td><td>Clients of each API</td><td>Service endpoints on the compose networks</td></tr>
<tr><td>REGISTRY_PUBLISHER_TOKEN, REGISTRY_READER_TOKEN, REGISTRY_EVALUATOR_TOKEN, REGISTRY_CONTROL_TOKEN</td><td>Registry clients</td><td>Registry authentication; the control token is the only one allowed on pool write routes</td></tr>
<tr><td>FEEDBACK_READER_TOKEN</td><td>Research services, qfr-mcp</td><td>Feedback API authentication, mapped to allowed program ids</td></tr>
<tr><td>RESEARCH_CONTROL_TOKEN, EVAL_OWNER_TOKEN</td><td>qfr-mcp, research-api, eval-admin-api</td><td>The front door's credentials for the research control API and the eval admin API</td></tr>
<tr><td>QFR_MCP_TOKEN, QFR_MCP_BIND</td><td>qfr-mcp, the host agent</td><td>The owner's bearer token and the loopback bind address (default 127.0.0.1:8765)</td></tr>
<tr><td>DEEPSEEK_API_KEY, MOONSHOT_API_KEY, ZHIPU_API_KEY</td><td>research-worker only</td><td>Provider credentials. Names are fixed; the providers.yaml file references them by name</td></tr>
<tr><td>QFR_RESEARCH_SNAPSHOT_DIR, QFR_FULL_SNAPSHOT_DIR</td><td>Workbench and evaluation</td><td>Snapshot mount points</td></tr>
<tr><td>QFR_EPOCH_CONFIG</td><td>Evaluation only</td><td>Path to the epoch window definitions</td></tr>
<tr><td>QFR_BUDGET_CURRENCY, QFR_GENERATION_COST_CAP, QFR_DAILY_COST_CAP</td><td>research-worker</td><td>Budget currency (default CNY) and caps; override the charter defaults</td></tr>
<tr><td>QFR_LOG_DIR, QFR_LOG_LEVEL, QFR_ENV, TZ</td><td>All services</td><td>Log directory on the shared volume, verbosity, environment (dev, test, prod) and time zone (Asia/Shanghai)</td></tr>
<tr><td>QFR_IMPORTS_DIR, QFR_EXPORTS_DIR</td><td>qfr-mcp, setup CLI</td><td>Owner-facing folders for raw pool files and exported bundles</td></tr>
</tbody>
</table>
</div>
</section>
<!-- ===================================================== CHAPTER 6 -->
<section class="chapter" id="ch-6">
<div class="chapter-kicker"><span class="n">6</span>Chapter 6</div>
<h2>Market data, data zones and timing conventions<a class="anchor" href="#ch-6">#</a></h2>

<h3 id="s-6-1"><span class="sn">6.1</span>Sources</h3>
<ul>
  <li><strong>S1. Synthetic market generator</strong> (mandatory, Phase 1). Used by every automated test and benchmark.</li>
  <li><strong>S2. China A-share daily data</strong> from the chenditc/investment_data GitHub releases: the <code>qlib_bin.tar.gz</code> archive plus its <code>qlib_bin.manifest.json</code>. CSI 300 is the default universe and CSI 500 is optional. The dataset merges several sources, is updated daily, keeps delisted companies and includes index-constituent files with date ranges.</li>
  <li><strong>S3. Later:</strong> an industry-classification dataset (for neutralization) and a US-equities adapter interface (which needs a point-in-time vendor). Both are in Phase 8.</li>
</ul>

<h3 id="s-6-2"><span class="sn">6.2</span>Qlib binary format reader</h3>
<p>The system reads the format directly and <span class="kw">MUST NOT</span> depend on the qlib package.</p>
<ul>
  <li><code>calendars/day.txt</code>: one trading date per line, in ascending order.</li>
  <li><code>instruments/&lt;universe&gt;.txt</code>: tab-separated lines of symbol, start date and end date. A symbol may appear on several lines if it re-entered the index. This file is the point-in-time membership.</li>
  <li><code>features/&lt;symbol&gt;/&lt;field&gt;.day.bin</code>: a little-endian float32 array. Element 0 is the start index into the calendar. The remaining elements are the values for consecutive calendar dates from that index.</li>
  <li>Fields are discovered by listing the files. Required fields: open, high, low, close, volume, amount, factor. Optional fields: vwap, change. Ingest <span class="kw">MUST</span> fail with a clear error if a required field is missing.</li>
  <li>Price fields are adjusted. The raw price equals the adjusted price divided by factor. Ingest <span class="kw">MUST</span> verify this convention with a sanity check (99% of raw closes fall between 0.5 and 5,000 CNY) and record it in the snapshot manifest.</li>
  <li>The index series SH000300 is used as the CSI 300 benchmark when present. Otherwise the benchmark is the equal-weight universe return, and the manifest says so.</li>
  <li>The archive is validated against the release manifest (SHA-256) before extraction, and the release tag is recorded.</li>
  <li>Ingest sanity checks: non-positive prices or negative volumes are errors, as are duplicate dates. A daily absolute return above 25% on a main-board stock outside its first five trading days is flagged as a likely corporate-action mismatch.</li>
</ul>

<h3 id="s-6-3"><span class="sn">6.3</span>Canonical panel</h3>
<p>Snapshot layout: <code>snapshots/&lt;zone&gt;/&lt;snapshot_id&gt;/</code> containing <code>panel/year=YYYY/part.parquet</code>, <code>membership.parquet</code>, <code>calendar.parquet</code> and <code>manifest.json</code>.</p>
<p>The panel is dense. There is exactly one row per instrument per trading date between the instrument's first and last observation. Missing days carry nulls and <code>is_suspended</code> set to true. Because of this, rolling windows over rows are rolling windows over the market calendar.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Column</th><th>Type</th><th>Description</th></tr></thead>
<tbody>
<tr><td>date</td><td>date</td><td>Trading date</td></tr>
<tr><td>instrument</td><td>string</td><td>Exchange-prefixed code, for example SH600000</td></tr>
<tr><td>open, high, low, close</td><td>float64</td><td>Adjusted prices</td></tr>
<tr><td>close_raw</td><td>float64</td><td>close divided by factor</td></tr>
<tr><td>volume</td><td>float64</td><td>Volume, adjusted consistently with prices</td></tr>
<tr><td>amount</td><td>float64</td><td>Traded value</td></tr>
<tr><td>vwap</td><td>float64</td><td>VWAP when available, otherwise the mean of high, low and close</td></tr>
<tr><td>factor</td><td>float64</td><td>Adjustment factor</td></tr>
<tr><td>ret_1d</td><td>float64</td><td>Adjusted close-to-close return</td></tr>
<tr><td>is_suspended</td><td>bool</td><td>No trade on this day (volume zero or missing)</td></tr>
<tr><td>limit_up, limit_down</td><td>bool</td><td>Raw close at the board-specific price limit relative to the previous raw close. Main board 10%. STAR 20% from listing. ChiNext 20% from 2020-08-24, 10% before. ST names (5%) cannot be detected from this data, which is a documented limitation</td></tr>
<tr><td>listed_days</td><td>int32</td><td>Trading days since first observation</td></tr>
<tr><td>in_csi300, in_csi500</td><td>bool</td><td>Point-in-time membership flags</td></tr>
<tr><td>adv20</td><td>float64</td><td>20-day mean traded value, used as the size and liquidity proxy</td></tr>
</tbody>
</table>
</div>
<p>Snapshot manifest contents: source, release tag, archive hash, build code version, field list, conventions, date range, row counts, zone, research cutoff (research zone only). The <code>snapshot_id</code> is the SHA-256 of the canonical manifest JSON.</p>

<h3 id="s-6-4"><span class="sn">6.4</span>Data zones and evaluation windows</h3>
<ul>
  <li><strong>Research-zone snapshot:</strong> every row dated on or before the research cutoff (the end of W0). Built by truncation in the ingest job, mounted read-only into research containers, and never updated within an epoch.</li>
  <li><strong>Full snapshot:</strong> all rows. Mounted only into evaluation containers. Rebuilt daily for simulation, with a new snapshot id each day. Old snapshots are retained so official records stay reproducible.</li>
</ul>
<p>Default windows for epoch 1 are stored in <code>configs/epochs/epoch_001.yaml</code>, which only the evaluation side can read. The owner may read them through MCP; research agents cannot.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Window</th><th>Purpose</th><th>Default range</th><th>Research visibility</th><th>What is released to research</th></tr></thead>
<tbody>
<tr><td>W0 Research</td><td>Agents explore, fit and pre-screen</td><td>2010-01-04 to 2019-12-31</td><td>Full data</td><td>Nothing (research computes its own numbers)</td></tr>
<tr><td>W1 Feedback</td><td>First independent measurement</td><td>2020-02-04 to 2022-12-30</td><td>No data</td><td>Coarsened reports (<a href="#ch-9">Section 9</a>)</td></tr>
<tr><td>W2 Validation</td><td>Rationed confirmation</td><td>2023-02-01 to 2024-06-28</td><td>No data</td><td>Pass/fail plus Ladder status</td></tr>
<tr><td>W3 Private holdout</td><td>Acceptance gate only</td><td>2024-08-01 to the end of the last full month before the epoch starts</td><td>No data</td><td>Never. Only decisions</td></tr>
<tr><td>W4 Forward</td><td>Simulated trading after publication</td><td>First trading day after admission, until incubation ends</td><td>No data</td><td>Coarse summary when incubation ends</td></tr>
</tbody>
</table>
</div>
<p>Rules:</p>
<ul>
  <li>An embargo of at least 20 trading days (the longest label horizon) separates consecutive windows.</li>
  <li>A label is computed for window W only if the decision day t and the day t+1+h both lie inside W.</li>
  <li><strong>Contamination warning.</strong> W0 to W3 all fall inside the training data of current LLMs, and LLMs measurably memorize historical market outcomes. The DSL's lack of identifiers and dates limits direct exploitation, but period-specific knowledge can still leak into design choices. W4 is therefore the decisive evidence, and full acceptance requires it. Every deliverable states its evidence tier for this reason.</li>
</ul>

<h3 id="s-6-5"><span class="sn">6.5</span>Timing conventions</h3>
<p>The research workbench and the evaluator <span class="kw">MUST</span> use identical conventions.</p>
<ul>
  <li><strong>Decision time:</strong> after the close of trading day t. The factor value at t may use only data dated t or earlier.</li>
  <li><strong>Execution:</strong> at the close of day t+1 (protocol v2 <span class="kw">MAY</span> switch to the VWAP of t+1).</li>
  <li><strong>Forward return label</strong> for horizon h, in trading days: the adjusted close at t+1+h divided by the adjusted close at t+1, minus 1. The primary horizon is 1. Decay horizons are 1, 5, 10 and 20.</li>
  <li><strong>Eligible cross-section on day t:</strong> in the universe at t (point-in-time), listed for at least 60 days, not suspended at t, and both factor and label non-null. At least 30 names are required, otherwise the date is skipped.</li>
  <li><strong>Tradability</strong> in backtests and simulation: no trading on suspended days. No buying at the limit-up price on t+1. No selling at the limit-down price on t+1.</li>
  <li><strong>Cross-sectional preprocessing</strong> in the evaluator protocol: winsorize at the 1st and 99th percentiles per day, then z-score per day. A size-neutral variant (OLS residual on a constant and log adv20, per day) is computed as a diagnostic. Industry dummies are added once an industry dataset exists.</li>
</ul>

<h3 id="s-6-6"><span class="sn">6.6</span>Synthetic market generator</h3>
<p>Defaults: 300 instruments, 2,600 trading days, 10 industries, fixed seed. It writes the same canonical snapshot format.</p>
<ul>
  <li><strong>Returns:</strong> the next-day return of instrument i equals beta_i times the market return, plus the industry return, plus the sum over planted signals of alpha_k times the cross-sectional z-score of signal k at t, plus idiosyncratic noise.</li>
  <li><strong>Market return:</strong> normal with mean 0.0003 and standard deviation 0.012. <strong>Industry returns:</strong> normal with mean 0 and standard deviation 0.006. <strong>Beta:</strong> uniform between 0.6 and 1.4. <strong>Idiosyncratic noise:</strong> Student-t with 5 degrees of freedom, scaled to a daily volatility drawn between 1.5% and 3.5% per instrument.</li>
  <li><strong>Planted signals</strong> are computable in the DSL from past data:
    <ul>
      <li>A1, short-term reversal: minus the 5-day return. Target RankIC 0.035.</li>
      <li>A2, volume-shock continuation: the sign of today's return times (today's volume divided by its 20-day mean, minus 1), clipped. Target RankIC 0.025.</li>
      <li>A3, low-volatility tilt: decay world only. Switched off halfway through W2.</li>
    </ul></li>
  <li>The generator calibrates each alpha_k numerically (bisection on a calibration sample) to hit its target RankIC.</li>
  <li><strong>Volumes</strong> are lognormal, with AR(1) log-volume (coefficient 0.8) and shocks correlated with absolute returns.</li>
  <li><strong>Realism features</strong> that exercise the pipeline: 5% of names enter or leave the universe each year, 0.5% of days are random suspensions, and price limits are 10%.</li>
  <li>The benchmark is the equal-weight universe return.</li>
  <li><strong>Three worlds:</strong> planted (A1, A2), null (every alpha is 0), decay (A1, A2, A3 with switch-off).</li>
  <li>A ground-truth file listing the planted signals as DSL expressions is written for the evaluation side and the benchmark harness only. It is test infrastructure, never a default factor set.</li>
</ul>
</section>

<!-- ===================================================== CHAPTER 7 -->
<section class="chapter" id="ch-7">
<div class="chapter-kicker"><span class="n">7</span>Chapter 7</div>
<h2>Factor DSL and artifact contract<a class="anchor" href="#ch-7">#</a></h2>

<h3 id="s-7-1"><span class="sn">7.1</span>Why a DSL first</h3>
<ul>
  <li>No arbitrary code execution in the MVP, and fully deterministic results.</li>
  <li>Lookahead-safe by construction: no negative lags and no access to the future.</li>
  <li>No access to dates or instrument identifiers, which closes the memorization and date-switching gaming channels.</li>
  <li>Canonical forms make exact dedup and AST similarity cheap.</li>
  <li>Syntactic mutation and crossover become trivial tree operations, and every mutation is a diff the trace can show.</li>
  <li>Imported raw-pool factors and factors extracted from an owner's documents are written in the same language, so they enter the same pipeline with no special path.</li>
</ul>

<h3 id="s-7-2"><span class="sn">7.2</span>Grammar</h3>
<ul>
  <li>An expression is a number, a field, a function call, a binary operation (+, -, *, /), a comparison (&gt;, &lt;, &gt;=, &lt;=, which yields 1.0 or 0.0), or a unary minus.</li>
  <li>Fields: <code>$open</code>, <code>$high</code>, <code>$low</code>, <code>$close</code>, <code>$vwap</code>, <code>$volume</code>, <code>$amount</code>, <code>$ret</code>, <code>$adv20</code>, <code>$close_raw</code>.</li>
  <li>Window arguments <span class="kw">MUST</span> be integer literals from the allowed set: 1, 2, 3, 5, 10, 20, 40, 60, 120, 250.</li>
  <li>Other numeric constants: at most 3 per expression, between -10 and 10, with at most 2 decimals. This prevents constant tuning.</li>
  <li>There are no variables, no user-defined functions, no date or identifier access and no string literals.</li>
</ul>

<h3 id="s-7-3"><span class="sn">7.3</span>Operator catalog for v1</h3>
<p>Time-series operators run per instrument over the dense calendar. An output is valid if at least ceil(0.8 × d) of the d inputs are valid when d is 5 or more, or if all inputs are valid when d is below 5. Otherwise the output is null.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Operator</th><th>Semantics</th></tr></thead>
<tbody>
<tr><td>Ref(x, d)</td><td>Value d days ago. d must be at least 1. Negative lags are a parse error</td></tr>
<tr><td>Delta(x, d)</td><td>x minus Ref(x, d)</td></tr>
<tr><td>Pct(x, d)</td><td>x divided by Ref(x, d), minus 1</td></tr>
<tr><td>Mean, Sum, Std, Var, Min, Max, Med (x, d)</td><td>Rolling statistics. Std and Var use ddof 1</td></tr>
<tr><td>EMA(x, d)</td><td>Exponential mean with alpha 2/(d+1), no adjustment, min periods d</td></tr>
<tr><td>WMA(x, d)</td><td>Linearly decaying weights d down to 1 (decay-linear)</td></tr>
<tr><td>TsRank(x, d)</td><td>Rank of today's value among the last d values, scaled to 0..1</td></tr>
<tr><td>TsZ(x, d)</td><td>(x minus Mean(x, d)) divided by Std(x, d)</td></tr>
<tr><td>ArgMax, ArgMin (x, d)</td><td>Days since the window maximum or minimum, where 0 means today</td></tr>
<tr><td>Corr, Cov (x, y, d)</td><td>Rolling Pearson correlation and covariance</td></tr>
<tr><td>Slope, Rsq, Resi (x, d)</td><td>Rolling regression of x on a time index: slope, R squared, last residual</td></tr>
<tr><td>Skew, Kurt (x, d)</td><td>Rolling skewness and excess kurtosis</td></tr>
</tbody>
</table>
</div>
<p>Cross-sectional operators run per date over the eligible cross-section.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Operator</th><th>Semantics</th></tr></thead>
<tbody>
<tr><td>Rank(x)</td><td>Percentile rank in 0..1, ties averaged</td></tr>
<tr><td>Zscore(x)</td><td>(x minus mean) divided by standard deviation</td></tr>
<tr><td>Demean(x)</td><td>x minus the cross-sectional mean</td></tr>
<tr><td>Scale(x)</td><td>x divided by the sum of absolute values</td></tr>
<tr><td>Neutralize(x)</td><td>OLS residual on a constant and log adv20 (industry added when available)</td></tr>
</tbody>
</table>
</div>
<p>Element-wise operators: Abs, Sign, Log (null for non-positive input), Sqrt (null for negative input), SignedPower(x, p) with p in 0.5, 2 or 3, Clip(x, lo, hi), Max2(x, y), Min2(x, y), If(condition, a, b).</p>
<p>Numeric rules: division by a denominator whose absolute value is below 1e-12 yields null, and infinities become null. Operators are implemented as Polars expressions over the panel sorted by instrument and date: grouped by instrument for time-series operators and by date for cross-sectional ones. Every operator also gets a naive loop-based reference implementation, used only in tests.</p>

<h3 id="s-7-4"><span class="sn">7.4</span>Static constraints</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Constraint</th><th>Limit</th></tr></thead>
<tbody>
<tr><td>AST nodes</td><td>30 or fewer</td></tr>
<tr><td>Depth</td><td>7 or fewer</td></tr>
<tr><td>Distinct fields</td><td>4 or fewer</td></tr>
<tr><td>Non-window numeric constants</td><td>3 or fewer</td></tr>
<tr><td>Total lookback along any root-to-leaf path</td><td>250 days or fewer</td></tr>
<tr><td>Nesting of Corr or Cov</td><td>2 levels or fewer</td></tr>
</tbody>
</table>
</div>
<p>The complexity score is nodes + 2 × constants + 3 × distinct fields. It is reported in every report and used as a fitness penalty.</p>

<h3 id="s-7-5"><span class="sn">7.5</span>Canonicalization, hashing and similarity</h3>
<ul>
  <li><strong>Canonical form:</strong> parse, then normalize. Children of commutative operators (+, *, Max2, Min2) are sorted by their canonical string. Double negation is removed, constants are folded, and Rank(Rank(x)) becomes Rank(x). The result is serialized to a compact string. <code>canonical_hash</code> is the SHA-256 of that string.</li>
  <li><strong>AST similarity:</strong> the size of the largest common subtree divided by the node count of the larger tree, computed with memoized top-down matching. Originality is 1 minus the maximum similarity against the library and the population.</li>
  <li><strong>AST diff:</strong> a deterministic, minimal edit script between two canonical trees (node insertions, deletions, substitutions and window changes). It is stored on every lineage edge and rendered in iteration histories.</li>
  <li><strong>Behavioral fingerprint:</strong> the factor's cross-sectional ranks on 40 fixed dates, sampled once per epoch from W0 with a fixed seed. Behavioral similarity between two factors is the mean, over those dates, of the absolute Spearman correlation on common names. Both zones compute it with the same qfr_core code because W0 is visible to both.</li>
</ul>

<h3 id="s-7-6"><span class="sn">7.6</span>Artifact kinds</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Kind</th><th>Phase</th><th>Payload</th><th>Evaluation</th><th>Pool</th></tr></thead>
<tbody>
<tr><td>factor</td><td>2</td><td>DSL expression (Python module from Phase 8)</td><td>Screening, W1, W2, W3, and W4 through the reference strategy</td><td>Factor pool</td></tr>
<tr><td>strategy</td><td>6</td><td>References to published factor versions, a combination rule and portfolio rules (<a href="#s-7-8">Section 7.8</a>). Richer rules in Phase 8</td><td>Composite recomputed by the evaluator, then backtests on W1 to W3 and simulation</td><td>Strategy pool</td></tr>
<tr><td>research_note</td><td>8</td><td>Markdown plus structured claims citing released report ids</td><td>Output-quality checks only</td><td>None</td></tr>
</tbody>
</table>
</div>
<p>All kinds use the same publication contract, the same read-only feedback contract and the same trace requirements.</p>

<h3 id="s-7-7"><span class="sn">7.7</span>Factor manifest (schema version 1)</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Field</th><th>Required</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>schema_version</td><td>Yes</td><td>The string "1"</td></tr>
<tr><td>kind</td><td>Yes</td><td>"factor"</td></tr>
<tr><td>family_id</td><td>Yes</td><td>Null asks the registry to create a new family. Otherwise the publication becomes the next version of that family</td></tr>
<tr><td>name</td><td>Yes</td><td>Slug of 64 characters or fewer, unique within the program</td></tr>
<tr><td>title</td><td>Yes</td><td>120 characters or fewer</td></tr>
<tr><td>implementation.language</td><td>Yes</td><td>"qfr-dsl/1"</td></tr>
<tr><td>implementation.expression</td><td>Yes</td><td>1,000 characters or fewer</td></tr>
<tr><td>declared.expected_sign</td><td>Yes</td><td>+1 or -1. A pre-registered direction</td></tr>
<tr><td>declared.horizon_days</td><td>Yes</td><td>1, 5, 10 or 20</td></tr>
<tr><td>declared.fields_used</td><td>Yes</td><td>Must equal the parsed field set (checked)</td></tr>
<tr><td>declared.max_lookback_days</td><td>Yes</td><td>Must equal the computed lookback (checked)</td></tr>
<tr><td>rationale.hypothesis_id</td><td>Yes</td><td>Blackboard hypothesis id. For imported seeds, the id of the auto-created seed hypothesis</td></tr>
<tr><td>rationale.summary</td><td>Yes</td><td>1,500 characters or fewer</td></tr>
<tr><td>rationale.mechanism</td><td>Yes</td><td>The economic mechanism, 1,500 characters or fewer</td></tr>
<tr><td>rationale.falsification</td><td>Yes</td><td>The result that would refute the hypothesis, 600 characters or fewer</td></tr>
<tr><td>rationale.change_summary</td><td>When a parent exists</td><td>What changed relative to the parent and why, 600 characters or fewer</td></tr>
<tr><td>provenance.job_id</td><td>Yes</td><td>The owner's research job this version was developed under. Null only for setup imports</td></tr>
<tr><td>provenance.program_id, generation_id, island_id</td><td>Yes</td><td>Research identifiers. Null for setup imports</td></tr>
<tr><td>provenance.operator</td><td>Yes</td><td>explore, llm_mutation, syntactic_mutation, crossover, repair or human_seed</td></tr>
<tr><td>provenance.parent_version_ids</td><td>Yes</td><td>List, possibly empty</td></tr>
<tr><td>provenance.agent_runs</td><td>Yes</td><td>For each run: role, provider, model id, prompt template id, prompt SHA-256, run id</td></tr>
<tr><td>provenance.trace_ref</td><td>Yes</td><td>The candidate id whose trace steps describe this version's development (<a href="#ch-14">Section 14</a>)</td></tr>
<tr><td>provenance.research_snapshot_id</td><td>Yes</td><td>The research data used during development</td></tr>
<tr><td>provenance.qfr_core_version</td><td>Yes</td><td>Semantic version</td></tr>
<tr><td>self_assessment</td><td>No</td><td>Research-side W0 numbers, labelled non-official. The evaluator never uses them in decisions</td></tr>
<tr><td>review.verdict_id, review.rounds</td><td>Yes</td><td>Critic sign-off. For setup imports, the deterministic validation record</td></tr>
</tbody>
</table>
</div>
<p>Fields assigned by the registry: <code>version_id</code> (UUIDv7), <code>version_no</code> (1 to n within the family), <code>content_hash</code> (SHA-256 of the canonical JSON manifest excluding server fields), <code>canonical_hash</code> (DSL), <code>published_at</code>, <code>published_seq</code> (monotonic) and the publisher principal.</p>
<p>Publication rules:</p>
<ul>
  <li>Publication is idempotent on <code>content_hash</code>: republishing identical content returns the existing version.</li>
  <li>A sign flip, a window change or any other edit creates a new version, and that version counts as a new trial.</li>
  <li>There is no retraction. Research may mark a family as abandoned only inside its own blackboard. The owner may retire a pool entry, which is a pool event, not a change to the version.</li>
</ul>

<h3 id="s-7-8"><span class="sn">7.8</span>Strategy manifest (schema version 1)</h3>
<p>v1 strategies are deliberately narrow: a weighted combination of published factor versions, run through the reference portfolio rules. This is enough for "create a momentum-style strategy" and "design a new strategy from these factors", and it reuses the evaluator's existing backtester. Richer rules arrive in Phase 8.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Field</th><th>Required</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>schema_version, kind, family_id, name, title</td><td>Yes</td><td>As for factors, with kind "strategy"</td></tr>
<tr><td>implementation.language</td><td>Yes</td><td>"qfr-strategy/1"</td></tr>
<tr><td>implementation.components</td><td>Yes</td><td>1 to 8 entries of {version_id, sign, weight}. Each version_id is a published factor version that passed screening. Weights are positive and normalized to sum to 1 by the registry; the client sends raw weights with at most 2 decimals</td></tr>
<tr><td>implementation.combination</td><td>Yes</td><td>"zscore_weighted_sum": per day, winsorize and z-score each component cross-sectionally, multiply by sign and weight, sum. The only v1 option</td></tr>
<tr><td>implementation.portfolio</td><td>Yes</td><td>{type: "topk_dropout", top_k, dropout, rebalance: "daily", long_only: true}. top_k in 20..100, dropout in 1..20. Costs always come from the protocol</td></tr>
<tr><td>declared.expected_sign, declared.horizon_days</td><td>Yes</td><td>Composite direction is always +1 after signs are applied; horizon as for factors</td></tr>
<tr><td>rationale.*</td><td>Yes</td><td>As for factors, plus composition_rationale (why these components and weights, 1,000 characters or fewer)</td></tr>
<tr><td>provenance.*</td><td>Yes</td><td>As for factors. parent_version_ids lists the component versions and any parent strategy</td></tr>
<tr><td>self_assessment, review.*</td><td>As for factors</td><td>W0 composite statistics, non-official</td></tr>
</tbody>
</table>
</div>
<ul>
  <li>The registry computes the strategy's <code>canonical_hash</code> from the sorted components (version id, sign, normalized weight rounded to 0.01) and the portfolio parameters.</li>
  <li>The evaluator never trusts component values from research. It recomputes every component from its own registry copy of the expression on the full snapshot, forms the composite, and runs the strategy plugin (<a href="#s-8-10">Section 8.10</a>).</li>
  <li>Strategy gates are listed in <a href="#s-8-8">Section 8.8</a>. Strategy deliverables carry the reference-strategy statistics, the NAV series and the per-component contribution table.</li>
</ul>

<h3 id="s-7-9"><span class="sn">7.9</span>Lifecycle</h3>
<p>Research-side candidate states: <code>draft</code>, then <code>in_review</code>, then <code>approved</code> or <code>rejected</code>. Approved candidates become <code>selected</code> or <code>not_selected</code>, and selected ones become <code>published</code> once a version id exists.</p>
<p>Evaluation-side version states, which the evaluator owns and which the owner can read in full through MCP:</p>
<figure id="fig-3">
<div class="flow">
  <div class="st">Discovered<small>pulled from the registry</small></div><span class="arrow">→</span>
  <div class="st bad">IntakeRejected<small>schema or kind invalid</small></div>
  <div class="st bad">Duplicate<small>same canonical hash or behaviour</small></div>
  <div class="st wait">Deferred<small>quota exceeded; expires after 7 days</small></div><span class="arrow">→</span>
  <div class="st">Screening<small>static checks, coverage, lookahead probe, runtime</small></div><span class="arrow">→</span>
  <div class="st bad">ScreenFailed</div>
  <div class="st good">W1Evaluated<small>official record; coarsened report released</small></div><span class="arrow">→</span>
  <div class="st bad">W1GateFailed</div>
  <div class="st">W2Queued<small>family W2 quota</small></div><span class="arrow">→</span>
  <div class="st bad">W2Failed</div>
  <div class="st">HoldoutCheck<small>W3, once per version, private</small></div><span class="arrow">→</span>
  <div class="st bad">NotAdvanced</div>
  <div class="st wait">AwaitingSlot<small>simulation slot</small></div><span class="arrow">→</span>
  <div class="st">Incubating<small>W4 forward, 60 trading days</small></div><span class="arrow">→</span>
  <div class="st">AcceptanceReview<small>automated gates, case opened</small></div><span class="arrow">→</span>
  <div class="st owner">Accepted or Rejected<small>owner decision through MCP</small></div><span class="arrow">→</span>
  <div class="st">Monitoring<small>rolling RankIC, alerts</small></div><span class="arrow">→</span>
  <div class="st bad">Retired<small>decay alert or owner retirement</small></div>
</div>
<p style="margin:14px 0 6px;font-size:14px;color:var(--muted)">Owner-side pool status for a factor or strategy version, decided only through approval records (<a href="#s-10-4">Section 10.4</a>). The evidence tier is read from the evaluator and shown next to it:</p>
<div class="ladder">
  <div class="rung"><b>seed</b><span>imported raw-pool entry; evaluated like any version; counts as library for correlation checks after its W1 record</span></div>
  <div class="rung owner"><b>approved · w1_pass</b><span>owner approved a deliverable at the W1 tier</span></div>
  <div class="rung owner"><b>approved · w2_pass</b><span>owner approved after W2 PASS</span></div>
  <div class="rung owner"><b>approved · advanced / incubated</b><span>owner approved after holdout advancement, or after incubation and an accepted case</span></div>
  <div class="rung"><b>retired</b><span>owner retired the entry, or accepted a decay alert; stays in history</span></div>
</div>
<figcaption><b>Figure 3. Lifecycle.</b> Evaluation states (top) belong to the evaluator and progress on its schedule. Pool statuses (bottom) belong to the owner and change only through approval records written via MCP. A job's deliverable tier picks the evaluation state at which a result is handed to the owner.</figcaption>
<details class="src"><summary>Diagram source (Mermaid)</summary>
<pre><code>stateDiagram-v2
  [*] --&gt; Discovered
  Discovered --&gt; IntakeRejected: schema or kind invalid
  Discovered --&gt; Duplicate: same canonical hash or behaviour
  Discovered --&gt; Deferred: quota exceeded
  Deferred --&gt; Screening: quota available
  Deferred --&gt; IntakeRejected: deferral expired
  Discovered --&gt; Screening
  Screening --&gt; ScreenFailed: coverage, lookahead, runtime
  Screening --&gt; W1Evaluated
  W1Evaluated --&gt; W1GateFailed
  W1Evaluated --&gt; W2Queued: passes W1 gates
  W2Queued --&gt; W2Failed
  W2Queued --&gt; HoldoutCheck: passes W2 gates
  HoldoutCheck --&gt; NotAdvanced: fails private holdout
  HoldoutCheck --&gt; AwaitingSlot: passes
  AwaitingSlot --&gt; Incubating: simulation slot granted
  Incubating --&gt; AcceptanceReview: incubation complete
  AcceptanceReview --&gt; Rejected: owner decision
  AcceptanceReview --&gt; Accepted: gates pass and owner approves through MCP
  Accepted --&gt; Monitoring
  Monitoring --&gt; Retired: decay alert or owner retirement</code></pre>
</details>
</figure>
</section>
<!-- ===================================================== CHAPTER 8 -->
<section class="chapter" id="ch-8">
<div class="chapter-kicker"><span class="n">8</span>Chapter 8</div>
<h2>Independent evaluation system<a class="anchor" href="#ch-8">#</a></h2>

<h3 id="s-8-1"><span class="sn">8.1</span>Responsibilities</h3>
<p>The evaluation zone owns:</p>
<ul>
  <li>data ingest and snapshots, protocols and epochs;</li>
  <li>eligibility, quotas, run budget and priority;</li>
  <li>official computation, official records and the trial ledger;</li>
  <li>the release policy and the Feedback API;</li>
  <li>simulated trading, acceptance cases, the library (its view of the pools) and monitoring;</li>
  <li>owner-grade evidence served to the MCP front door through the eval admin API.</li>
</ul>
<p>It holds no LLM keys and no research credentials, and nothing on the research side can change its behavior except publishing artifacts. The owner changes its behavior only by activating new protocol, policy or quota versions through MCP.</p>

<h3 id="s-8-2"><span class="sn">8.2</span>Protocol definition</h3>
<p>A protocol is a versioned YAML file. It becomes immutable once activated, and any change means a new protocol version. Fields:</p>
<ul>
  <li>protocol_id and version;</li>
  <li>supported artifact kinds and the universe (csi300);</li>
  <li>label definition and horizons, and eligibility rules;</li>
  <li>preprocessing and neutralization diagnostics;</li>
  <li>the epoch reference for window dates;</li>
  <li>the metric list and the reference-strategy parameters;</li>
  <li>the costs, the gate thresholds for every stage and kind, and runtime limits;</li>
  <li>the fingerprint seed.</li>
</ul>
<p>From each protocol the evaluator derives a public <strong>protocol card</strong> for research and for the host agent. It includes the universe, label, timing conventions, metric definitions, cost assumptions and the W1 and W2 gates. Window dates, holdout rules and acceptance thresholds stay out of the card; the owner can read them through <code>qfr.config.get</code>, labelled owner-only.</p>

<h3 id="s-8-3"><span class="sn">8.3</span>Intake and eligibility</h3>
<p>The scheduler loop runs every 60 seconds.</p>
<ul>
  <li>Fetch up to 100 versions with <code>published_seq</code> greater than the intake cursor, and write an intake row for each (idempotent).</li>
  <li>Fetch pool events since the pool cursor and update the library (<a href="#s-10-4">Section 10.4</a>). Pool changes never trigger evaluation by themselves; a seed version is evaluated because it is a published version.</li>
  <li>Schema and kind check. Failures become IntakeRejected with SCHEMA_INVALID or KIND_UNSUPPORTED.</li>
  <li>Exact dedup. If the <code>canonical_hash</code> was seen before in any family, mark the version Duplicate with DUPLICATE_OF and the earlier version id.</li>
  <li>Behavioral dedup. If fingerprint similarity to an already evaluated version is 0.95 or more, mark it Duplicate with NEAR_DUPLICATE_OF. Duplicates are not evaluated and are not trials.</li>
  <li>Quota check (<a href="#s-9-3">Section 9.3</a>). If the quota is exceeded, the version becomes Deferred (QUOTA_DEFERRED) and is re-checked as capacity frees up. After 7 days it is rejected with QUOTA_EXPIRED.</li>
  <li>Enqueue a screening job. Priority is fair round-robin across families and first-in first-out within a family. Neither research nor the host agent has any way to influence priority.</li>
</ul>

<h3 id="s-8-4"><span class="sn">8.4</span>Screening</h3>
<ul>
  <li>Parse and type check, static constraints (<a href="#s-7-4">Section 7.4</a>), and declared-versus-parsed consistency for fields and lookback. For strategies: every component exists, passed screening, and the portfolio parameters are within range.</li>
  <li>Compute the factor once over the whole full snapshot in a single pass. Code can never tell which segment is being scored. For the DSL this is moot, but it keeps one code path ready for Python factors.</li>
  <li><strong>Coverage:</strong> the mean share of the eligible cross-section with a valid value across W1 dates must be at least 0.80. Only pass or fail is released.</li>
  <li><strong>Prefix-invariance probe:</strong> for 5 seeded random cut dates inside W1, recompute the factor on data truncated at each cut date. The values at the cut date must match the full-data values within 1e-9, with nulls treated as equal. Failure gives LOOKAHEAD_DETECTED.</li>
  <li><strong>Runtime limits:</strong> at most 120 seconds of CPU time and 4 GB of memory for the full computation. Failure gives RUNTIME_LIMIT.</li>
  <li><strong>Degeneracy:</strong> if the cross-sectional standard deviation is zero on more than 10% of dates, the result is DEGENERATE.</li>
</ul>

<h3 id="s-8-5"><span class="sn">8.5</span>Factor metrics</h3>
<p>These metrics are computed per window W. Notation: U(t) is the eligible set on day t; f(t) is the preprocessed factor and y(t, h) the label; s is the declared expected sign; quintile 5 holds the highest factor values; all long-short and portfolio results are sign-adjusted by s.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Metric</th><th>Definition</th></tr></thead>
<tbody>
<tr><td>IC(t)</td><td>Pearson correlation of f(t) and y(t, h) over U(t)</td></tr>
<tr><td>RankIC(t)</td><td>Spearman correlation, computed as Pearson on ranks with ties averaged</td></tr>
<tr><td>RankIC_mean, RankIC_std</td><td>Mean and standard deviation (ddof 1) of RankIC(t) over the window</td></tr>
<tr><td>RankIC_IR</td><td>RankIC_mean divided by RankIC_std, per period and not annualized</td></tr>
<tr><td>RankIC_t_NW</td><td>RankIC_mean divided by its Newey–West standard error (Bartlett kernel). The lag is the larger of h and floor(4 × (T/100)^(2/9))</td></tr>
<tr><td>Hit ratio</td><td>Share of dates on which s × RankIC(t) is positive</td></tr>
<tr><td>Sign consistency</td><td>s times the sign of RankIC_mean. Must be +1 to pass any gate</td></tr>
<tr><td>Decay profile</td><td>RankIC_mean for h = 1, 5, 10, 20</td></tr>
<tr><td>Quantile returns</td><td>Each day U(t) is split into 5 equal-count groups by f(t), with ties broken by instrument id. A group's return is the equal-weight mean of y(t, 1)</td></tr>
<tr><td>LS(t)</td><td>s × (quintile 5 return minus quintile 1 return)</td></tr>
<tr><td>LS gross Sharpe</td><td>mean(LS) / std(LS) × sqrt(252)</td></tr>
<tr><td>Top and bottom turnover</td><td>For the sign-adjusted top quintile set S(t): 1 minus size(S(t) ∩ S(t−1)) / size(S(t)). The same for the bottom set. Averaged over the window</td></tr>
<tr><td>LS net return and Sharpe</td><td>LS_net(t) = LS(t) − 2 × c × (top turnover(t) + bottom turnover(t)), with c = 10 bps per side. Sharpe as above</td></tr>
<tr><td>Monotonicity</td><td>s × the Spearman correlation between group index (1 to 5) and mean group return</td></tr>
<tr><td>Rank autocorrelation</td><td>Mean over t of Spearman(f(t), f(t−1)) on common names</td></tr>
<tr><td>Coverage</td><td>Mean share of the universe with a valid factor value</td></tr>
<tr><td>Library correlation</td><td>For each library factor g (seed or approved pool entries with a W1 record), the mean over t of Spearman(f(t), g(t)). The maximum absolute value and its argmax are reported. With an empty library the metric is null and the gate is vacuous, and the report says so</td></tr>
<tr><td>Size-neutral RankIC</td><td>RankIC_mean of the size-neutralized factor (diagnostic)</td></tr>
<tr><td>Yearly RankIC</td><td>RankIC_mean per calendar year (stability)</td></tr>
<tr><td>Reference strategy</td><td>Annualized net return, volatility, Sharpe, information ratio versus benchmark, maximum drawdown, Calmar ratio, turnover, average holding period (<a href="#s-8-6">Section 8.6</a>)</td></tr>
</tbody>
</table>
</div>
<p>Hand-computed fixtures: every metric gets a fixture of 3 to 5 instruments over 6 to 10 days with expected values stored in the test, worked out by hand and documented in the test file.</p>

<h3 id="s-8-6"><span class="sn">8.6</span>Reference backtest</h3>
<p>The reference backtest is deterministic. It is implemented as a daily loop over dates on NumPy arrays: correctness comes first, and vectorization is not required.</p>
<ul>
  <li>Long-only top-k, equal weight at entry, with k = 50 over CSI 300 and dropout n = 5 (TopK-dropout style). The score is s × f for factors and the composite for strategies. Strategies may set k and n within the ranges in <a href="#s-7-8">Section 7.8</a>.</li>
  <li>Each day: rank eligible names by score, breaking ties by instrument id; sell up to n holdings, choosing the lowest-scored among those ranked outside the top k; buy the highest-ranked names not already held, until there are k holdings again; buys are sized at current NAV divided by k from available cash; retained positions drift and are not rebalanced.</li>
  <li>Trades execute at the close of t+1. A blocked sell (suspended or limit-down) is retried the next day. A blocked buy moves on to the next candidate.</li>
  <li>Costs: 5 bps on buys and 15 bps on sells. The sell cost includes the CN stamp duty of 5 bps plus commission and slippage. Both are configurable.</li>
  <li>The backtest is weight-based: no lot sizes, notional capital 1.</li>
  <li>Outputs: a daily series of NAV, gross and net returns, turnover and holdings count, plus the metrics in <a href="#s-8-5">Section 8.5</a>. For strategies, a per-component contribution table (the composite's RankIC with each component removed).</li>
  <li>Hand-computed fixture: 3 stocks over 6 days with a hand-computed NAV path, including one blocked sell and one blocked buy.</li>
</ul>

<h3 id="s-8-7"><span class="sn">8.7</span>Multiple-testing and overfitting statistics</h3>
<p><strong>Probabilistic Sharpe Ratio</strong> (Bailey and López de Prado):</p>
<pre><code>PSR(SR*) = Φ( (SR − SR*) × sqrt(T − 1) / sqrt(1 − g3 × SR + ((g4 − 1) / 4) × SR²) )</code></pre>
<p>SR is the per-period, non-annualized Sharpe of daily returns. T is the number of returns. g3 is skewness and g4 is raw (Pearson) kurtosis, which equals 3 for a normal distribution, not excess kurtosis.</p>
<p><strong>Deflated Sharpe Ratio:</strong></p>
<pre><code>DSR = PSR(SR0),  where  SR0 = sqrt(V) × ( (1 − γ) × Φ⁻¹(1 − 1/N) + γ × Φ⁻¹(1 − 1/(N × e)) )</code></pre>
<ul>
  <li>γ ≈ 0.5772 is the Euler–Mascheroni constant.</li>
  <li>V is the variance of per-period Sharpe ratios across all trials on that window, taken from the trial ledger.</li>
  <li>N is N_eff, the number of behavioral clusters among those trials. Clusters are built by single-linkage grouping at fingerprint similarity 0.7 in a nightly job. If there are more than 20,000 trials, use the number of families instead.</li>
  <li>DSR is reported with both N_eff and the raw N. The gate uses N_eff.</li>
</ul>
<p><strong>Probability of Backtest Overfitting</strong>, by combinatorially symmetric cross-validation (Bailey, Borwein, López de Prado and Zhu):</p>
<ul>
  <li>Cohort: all versions in the version's family evaluated on W1. If there are fewer than 4, use the version's generation cohort. If still fewer than 4, skip the gate and record a note.</li>
  <li>Build the T × N matrix of daily W1 LS net returns. Split the rows into S = 16 contiguous blocks.</li>
  <li>For every combination of S/2 blocks used as in-sample (12,870 combinations): pick the version with the best in-sample Sharpe; compute its relative out-of-sample rank ω among the N versions, with ω strictly between 0 and 1; compute λ = ln(ω / (1 − ω)).</li>
  <li>PBO is the share of combinations with λ ≤ 0.</li>
</ul>
<p><strong>Harvey–Liu–Zhu hurdle:</strong> the Newey–West t-statistic of the mean daily LS net return over W1, W2 and W3 combined, with embargo gaps excluded, must be at least 3.0.</p>
<p>Each statistic gets a test against a published worked example or an independently computed fixture.</p>

<h3 id="s-8-8"><span class="sn">8.8</span>Gates</h3>
<p>All thresholds are evaluator-owned config. W1 and W2 gates are published in the protocol card. Holdout and acceptance gates are private to the evaluator and the owner.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Gate</th><th>Factor default rule</th><th>Strategy default rule</th></tr></thead>
<tbody>
<tr><td>W1 (public)</td><td>Sign consistency +1. s × RankIC_mean ≥ 0.02. RankIC_IR ≥ 0.12. RankIC_t_NW ≥ 2.5. Maximum absolute library correlation ≤ 0.70 (vacuous when the library is empty). Top turnover ≤ 0.60. Coverage passes</td><td>Composite RankIC_mean ≥ 0.02 and RankIC_t_NW ≥ 2.5. Reference net Sharpe ≥ 0.8. Information ratio versus benchmark ≥ 0.5. Maximum drawdown ≤ 25%. Composite correlation with any approved strategy ≤ 0.80</td></tr>
<tr><td>W2 (public)</td><td>Sign consistency +1. s × RankIC_mean ≥ 0.015. RankIC_IR ≥ 0.08. LS net Sharpe ≥ 0.5</td><td>Reference net Sharpe ≥ 0.5. Information ratio ≥ 0.3</td></tr>
<tr><td>Holdout W3 (private)</td><td>s × RankIC_mean ≥ 0.01. LS net Sharpe ≥ 0.3. Reference-strategy information ratio ≥ 0.3</td><td>Reference net Sharpe ≥ 0.3. Information ratio ≥ 0.3</td></tr>
<tr><td>Acceptance (private)</td><td colspan="2">See <a href="#s-10-3">Section 10.3</a></td></tr>
</tbody>
</table>
</div>
<p>When several versions of one family pass W1 within the same W2 quota period, the evaluator (not research, not the host agent) picks the one with the best W1 RankIC_IR. The others wait, and expire after 4 weeks.</p>

<h3 id="s-8-9"><span class="sn">8.9</span>Official records, the trial ledger and owner-grade evidence</h3>
<ul>
  <li>Every run pins its inputs: artifact version id and content hash; protocol id and version; epoch id and data snapshot id; evaluator git SHA, container image digest and seed.</li>
  <li>A run writes metric rows at full precision, series files (Parquet in the evaluation artifact store: daily IC, LS returns, NAV) and exactly one immutable official record. The record holds a JSON summary and a results hash, which is the SHA-256 of the canonical metrics JSON.</li>
  <li>The trial-ledger row is written in the same transaction. It holds the window, version id, family id, program id, job id, daily LS net Sharpe, number of observations, skewness, raw kurtosis and a fingerprint reference.</li>
  <li><code>qfr eval reproduce &lt;record_id&gt;</code> re-runs a record with its pinned inputs and compares the results hash.</li>
  <li><strong>Owner-grade evidence</strong> is the eval admin API's read of official records, gate values, series files and simulation state for one version. It is full precision and includes W3 where it exists. It is returned to the MCP front door only, carries <code>visibility: owner_only</code>, and is never cached in research_db. The deliverable's "backtesting results" are this evidence plus the released reports.</li>
</ul>

<h3 id="s-8-10"><span class="sn">8.10</span>Other kinds: plugins for strategy and research_note</h3>
<p>Each artifact kind implements a plugin interface: eligibility for a manifest; the ordered list of stages; a run function per stage that produces an official record payload; a release mapping that turns a record into whitelisted released fields; and an owner-grade mapping for the eval admin API.</p>
<ul>
  <li><strong>factor</strong> (Phase 3): as above.</li>
  <li><strong>strategy</strong> (Phase 6): recompute components from their expressions, form the composite, run screening on the composite (coverage, degeneracy, lookahead probe), then the reference backtest with the strategy's portfolio parameters on W1, W2 and W3, and simulation on W4. Released fields are the strategy counterparts of the factor fields (net Sharpe bucket, IR bucket, drawdown bucket, turnover, composite RankIC rounded).</li>
  <li><strong>research_note</strong> (Phase 8): schema completeness; every cited report id exists and was released; numeric claims match the released values within their rounding granularity; no references to undisclosed windows; length limits. These checks are deterministic. An optional LLM rubric score <span class="kw">MAY</span> be added later on the evaluation side, with a pinned model, temperature 0 and logged prompts. It would be advisory only and never part of a gate.</li>
</ul>
</section>

<!-- ===================================================== CHAPTER 9 -->
<section class="chapter" id="ch-9">
<div class="chapter-kicker"><span class="n">9</span>Chapter 9</div>
<h2>Feedback release policy and anti-overfitting controls<a class="anchor" href="#ch-9">#</a></h2>

<h3 id="s-9-1"><span class="sn">9.1</span>Principles</h3>
<p>Feedback is necessary for learning, but every released number leaks information about the evaluation windows. Adaptive data analysis research shows that repeatedly querying a holdout and acting on full-precision answers overfits it. It also shows that thresholding, coarsening and noise preserve validity: see the reusable holdout (Thresholdout) and the Ladder leaderboard mechanism. The release engine is therefore a first-class, versioned and tested component owned by the evaluator. The policy governs what <em>research agents</em> may see. The owner sees everything through MCP, with the hygiene rule in <a href="#s-9-6">Section 9.6</a>.</p>
<p>Results are never held back. Every report is released as soon as the evaluator records its decision, so research learns from each evaluation without delay. The safeguards work on content and count, not on time: coarsening, fixed enum codes and the Ladder limit how much each answer reveals; quotas, the trial ledger with DSR, and the burn meters limit and account for how many questions are asked; W3 is never released at all. Research already works in generations, publishing at most 12 versions and planning the next generation from their results, so the number of adaptive rounds is set by the generation loop. Holding a finished answer back would not change what it reveals or how many answers research receives, so timing is not used as a safeguard.</p>

<h3 id="s-9-2"><span class="sn">9.2</span>Release levels for the default_v1 policy</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Report type</th><th>Trigger</th><th>Released content</th><th>Precision</th><th>Timing</th></tr></thead>
<tbody>
<tr><td>intake</td><td>Intake decision</td><td>Status and reason code</td><td>Not applicable</td><td>Immediately</td></tr>
<tr><td>screening</td><td>Screening finished</td><td>Pass or fail and reason codes</td><td>Not applicable</td><td>Immediately</td></tr>
<tr><td>w1</td><td>W1 official record</td><td>RankIC_mean, RankIC_IR, NW t bucket, hit ratio, decay profile, LS net Sharpe, monotonicity, top turnover, rank autocorrelation, maximum library correlation with the library version id, yearly RankIC, coverage bucket, size-neutral RankIC, complexity, diagnostic flags. Strategy counterparts for strategies</td><td>RankIC values to 0.005. IR to 0.02. t in buckets: below 1, 1 to 2, 2 to 3, above 3. Sharpe to 0.25. Shares and correlations to 0.05</td><td>Immediately</td></tr>
<tr><td>w2</td><td>W2 official record</td><td>PASS or FAIL. Ladder status for the family. When the family best improved by at least η = 0.005, the new family best RankIC rounded to 0.01</td><td>Coarse</td><td>Immediately</td></tr>
<tr><td>advancement</td><td>Holdout check</td><td>ADVANCED or NOT_ADVANCED, with no numbers</td><td>1 bit</td><td>Immediately</td></tr>
<tr><td>sim</td><td>Incubation finished</td><td>Completion status. Forward RankIC bucket: negative, 0 to 0.01, 0.01 to 0.03, above 0.03. Forward Sharpe bucket</td><td>Coarse</td><td>Only when incubation ends</td></tr>
<tr><td>decision</td><td>Owner decision on an acceptance case</td><td>ACCEPTED or REJECTED with a reason category: gate failed (gate name), owner rejected, or incubation failed</td><td>Not applicable</td><td>Immediately</td></tr>
<tr><td>library</td><td>Pool change synced into the library</td><td>Library membership change: version id and new status</td><td>Not applicable</td><td>Immediately</td></tr>
</tbody>
</table>
</div>
<p>Never released to research:</p>
<ul>
  <li>any W3 metric;</li>
  <li>any daily or periodic series beyond the yearly W1 aggregates;</li>
  <li>W2 and W3 window dates;</li>
  <li>raw error text, run timings and queue positions;</li>
  <li>reports belonging to other programs;</li>
  <li>anything the owner wrote in a brief about evidence they have seen (the brief is text; see the hygiene rule below).</li>
</ul>
<p>Diagnostic flags (fixed enum):</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Flag</th><th>Meaning</th></tr></thead>
<tbody>
<tr><td>HIGH_TURNOVER</td><td>Top turnover too high</td></tr>
<tr><td>LOW_MONOTONICITY</td><td>Quintile returns are not monotone</td></tr>
<tr><td>SIGN_MISMATCH</td><td>Realized sign is opposite to the declared sign</td></tr>
<tr><td>CROWDED_WITH_LIBRARY</td><td>Too correlated with a library factor</td></tr>
<tr><td>UNSTABLE_YEARLY</td><td>Yearly sign flips</td></tr>
<tr><td>DECAYS_FAST</td><td>RankIC at h = 5 is below 40% of RankIC at h = 1</td></tr>
<tr><td>LOW_COVERAGE</td><td>Coverage too low</td></tr>
<tr><td>WEAK_SIGNAL</td><td>Signal too weak</td></tr>
<tr><td>COST_DOMINATED</td><td>Net Sharpe below 50% of gross</td></tr>
<tr><td>HIGH_DRAWDOWN</td><td>Strategies only: maximum drawdown above the gate</td></tr>
</tbody>
</table>
</div>
<p>Reason codes (fixed enum):</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Group</th><th>Codes</th></tr></thead>
<tbody>
<tr><td>Schema and parsing</td><td>SCHEMA_INVALID, KIND_UNSUPPORTED, PARSE_ERROR, TYPE_ERROR, COMPLEXITY_LIMIT, FORBIDDEN_CONSTRUCT, DECLARATION_MISMATCH, COMPONENT_INVALID</td></tr>
<tr><td>Dedup and quotas</td><td>DUPLICATE_OF, NEAR_DUPLICATE_OF, QUOTA_DEFERRED, QUOTA_EXPIRED</td></tr>
<tr><td>Screening</td><td>LOW_COVERAGE, LOOKAHEAD_DETECTED, RUNTIME_LIMIT, DEGENERATE</td></tr>
<tr><td>Internal</td><td>INTERNAL_ERROR (retried first, then released without detail; the full error is in the logs for the owner)</td></tr>
</tbody>
</table>
</div>

<h3 id="s-9-3"><span class="sn">9.3</span>Quotas</h3>
<p>All quotas are owned by the evaluator and changed only by activating a new quota version through MCP.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Scope</th><th>W1</th><th>W2</th><th>W3 and simulation</th></tr></thead>
<tbody>
<tr><td>Per family</td><td>3 per rolling 24 hours</td><td>1 per 7 days</td><td>W3 once per version</td></tr>
<tr><td>Per program (one job)</td><td>60 per day</td><td>10 per week</td><td></td></tr>
<tr><td>Global</td><td>200 per day (worker capacity)</td><td>400 per epoch (the W2 query budget)</td><td>100 W3 per epoch. 40 concurrent simulation slots</td></tr>
</tbody>
</table>
</div>
<p>Quotas limit how many versions are evaluated per family, per program and in total. That bounds the number of trials DSR and the burn meters account for, and stops one family from being probed many times a day; the global limits match worker capacity. Quotas never hold back a finished result. A version over quota receives a <code>QUOTA_DEFERRED</code> intake report at once, is evaluated when room opens, and is rejected with <code>QUOTA_EXPIRED</code> after 7 days. Owner-grade evidence is readable as soon as the official record exists, at the same moment research receives the coarsened report.</p>

<h3 id="s-9-4"><span class="sn">9.4</span>Burn accounting</h3>
<p>For each window in each epoch, the evaluator tracks the trial count, the number of released numeric values, W2 queries used against budget, and W3 queries used. Burn-meter thresholds:</p>
<ul>
  <li>W1 turns amber at 3,000 trials and red at 6,000.</li>
  <li>W2 turns red when its budget is exhausted.</li>
</ul>
<p>A red meter raises an alert that the host agent sees in <code>qfr.ops.alerts</code> and in <code>qfr.status</code>, prompting the owner to schedule an epoch rollover (<a href="#s-10-6">Section 10.6</a>). Meanwhile W1 feedback continues, and the DSR gate automatically gets stricter as N grows.</p>

<h3 id="s-9-5"><span class="sn">9.5</span>Optional Thresholdout mode for W2 (Phase 8)</h3>
<p>This follows Dwork et al.</p>
<ul>
  <li>The query statistic is s × RankIC_mean. The evaluator computes it on W0 itself, and on W2.</li>
  <li>Parameters: threshold T = 0.01, noise scale σ = 0.002, overfitting budget B = 50.</li>
  <li>Initialization: the noisy threshold is T plus Laplace(2σ) noise.</li>
  <li>Per query: draw Laplace(4σ) noise; if the absolute difference between the W2 and W0 values exceeds the noisy threshold plus that noise, release the W2 value plus Laplace(σ) noise, decrement B and redraw the noisy threshold; otherwise release the W0 value, which means "consistent with in-sample".</li>
  <li>When B falls below 1, W2 answers nothing until the next rollover.</li>
  <li>The random generator is seeded and every draw is logged for audit.</li>
</ul>

<h3 id="s-9-6"><span class="sn">9.6</span>What research is told, and what the owner sees</h3>
<p>The Feedback API serves two public cards: the <strong>policy card</strong> (what is released, at what precision, when, and under which quotas) and the <strong>protocol card</strong> (universe, label, costs, metric definitions, and W1 and W2 gates). Agents can plan with both. Window dates, W3 rules and acceptance thresholds stay private to the evaluator and the owner.</p>
<div class="callout warn"><span class="ico">!</span><div><b class="t">Holdout hygiene through the owner channel</b>
<p>The owner may read owner-grade evidence, including W3 numbers, through MCP. A brief or steering note is free text that reaches research prompts. If the owner or the host agent pastes owner-only numbers into a brief, the holdout leaks through the front door. Three controls apply: (1) owner-grade evidence objects are never attachable to a brief, only ids are; (2) <code>qfr.job.submit</code> and <code>qfr.job.steer</code> run a deterministic scan that rejects text containing values that match any owner-only metric of a referenced version to its released or full precision, and logs the attempt; (3) the host-agent guide (<a href="#s-21-3">Section 21.3</a>) tells the host agent never to quote owner-only numbers in briefs. Residual risk is accepted by the owner and recorded in <code>docs/decisions.md</code>.</p></div></div>
</section>

<!-- ===================================================== CHAPTER 10 -->
<section class="chapter" id="ch-10">
<div class="chapter-kicker"><span class="n">10</span>Chapter 10</div>
<h2>Acceptance, simulated trading, pools and promotion<a class="anchor" href="#ch-10">#</a></h2>

<h3 id="s-10-1"><span class="sn">10.1</span>Flow after W2</h3>
<ul>
  <li>W2 pass leads to the holdout check: W3, run once per version, with private results.</li>
  <li>A pass enters AwaitingSlot, then forward incubation (W4) once a simulation slot is free.</li>
  <li>When incubation completes, an acceptance case is opened and the automated gates run.</li>
  <li>The owner decides through MCP (<code>qfr.acceptance.decide</code> with an approval record).</li>
  <li>Accepted versions are offered for the pool if not yet there, their pool entry records the <code>incubated</code> tier if already there, and they enter monitoring.</li>
</ul>
<p>None of this waits for the owner's deliverable workflow. A job may have delivered the same version weeks earlier at the <code>w1_pass</code> tier; the evaluator keeps evaluating, and the pool entry's evidence tier keeps improving or a decay alert appears. The owner sees both in <code>qfr.pool.list</code>.</p>

<h3 id="s-10-2"><span class="sn">10.2</span>Simulated trading engine</h3>
<ul>
  <li><strong>Inputs:</strong> a version (a factor runs through the reference strategy, and a strategy artifact uses its own portfolio rules) and a start date: the first trading day after the later of the publication date and the admission date. There is no backfill. Simulation uses only data that arrived after the artifact was published.</li>
  <li><strong>Daily cycle</strong>, triggered after daily ingest builds the new full snapshot (around 18:30 Asia/Shanghai). For new day d: fill the orders created at d−1 at the raw close of d, applying tradability rules, 100-share lots and costs, then update positions and cash; compute factor values at d and create target orders for d+1; mark to market at the close of d and write NAV. This matches the decision-at-t, execute-at-t+1 convention.</li>
  <li><strong>Capital:</strong> 100,000,000 CNY notional. Splits and dividends are approximated by scaling shares with the ratio of consecutive adjustment factors.</li>
  <li><strong>Modes:</strong> forward (production) and replay (tests and benchmarks only; it replays a reserved historical tail as if it were live and is never valid for real acceptance).</li>
  <li><strong>Data revisions:</strong> if a new release revises past values, the engine continues from its recorded state without recomputing history and logs a DATA_REVISION event.</li>
  <li>Incubation lasts 60 trading days by default. Checkpoints every 20 days are recorded, visible to the owner immediately, and released to research only when incubation ends.</li>
  <li><strong>Staleness:</strong> if no new data arrives for 2 trading days, raise an alert and pause the simulation clocks.</li>
</ul>

<h3 id="s-10-3"><span class="sn">10.3</span>Acceptance case and gates</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Gate</th><th>Default rule</th></tr></thead>
<tbody>
<tr><td>G-W1, G-W2</td><td>The respective gates passed</td></tr>
<tr><td>G-HOLDOUT</td><td>The holdout gate passed</td></tr>
<tr><td>G-DSR</td><td>DSR on W1 LS net returns with N_eff ≥ 0.90</td></tr>
<tr><td>G-PBO</td><td>PBO (CSCV, S = 16) on the cohort ≤ 0.30, or skipped with a recorded reason</td></tr>
<tr><td>G-HLZ</td><td>Newey–West t of LS net returns over W1, W2 and W3 ≥ 3.0</td></tr>
<tr><td>G-FWD</td><td>Incubation of at least 60 days. Forward s × RankIC_mean above 0. Consistency z ≥ −1.645 (see below). Forward maximum drawdown ≤ 15%</td></tr>
<tr><td>G-NOVELTY</td><td>Maximum absolute correlation with approved library entries on W3 ≤ 0.60 (vacuous when the library is empty)</td></tr>
<tr><td>G-OPS</td><td>No simulation errors, and at least 98% of days with complete data</td></tr>
</tbody>
</table>
</div>
<p>The consistency z for G-FWD is the forward RankIC mean minus the historical RankIC mean, divided by (the historical daily RankIC standard deviation divided by the square root of the number of forward days). Historical values are taken over W1 to W3.</p>
<ul>
  <li>The recommendation is ACCEPT if every gate passes. Otherwise it is REJECT, listing the failing gates.</li>
  <li>The owner <span class="kw">MAY</span> reject an ACCEPT recommendation, with a written rationale.</li>
  <li>In v1 a failed gate can never be accepted. Phase 8 adds an owner override that requires a written rationale, a 24-hour cooling period and a second confirmation.</li>
  <li>Gate values are visible to the owner through MCP only.</li>
</ul>

<h3 id="s-10-4"><span class="sn">10.4</span>Pools, library and monitoring</h3>
<p>The <strong>factor pool</strong> and the <strong>strategy pool</strong> are the owner's long-lived, curated collections. They live in <code>registry_db</code> as append-only entries and events (<a href="#s-16-1">Section 16.1</a>), and every entry references an immutable artifact version and an approval record. They are the system's memory across jobs.</p>
<ul>
  <li><strong>Who writes them:</strong> only the MCP front door, on the owner's behalf, through the registry's pool routes with the control token. Research code never writes a pool. The evaluator never writes a pool.</li>
  <li><strong>How they start:</strong> empty, unless the owner imports a raw factor pool at setup (<a href="#s-13-6">Section 13.6</a>). There are no default factors and no default strategies anywhere in the code or configuration.</li>
  <li><strong>Statuses:</strong> <code>seed</code> (imported at setup), <code>approved</code> with an <code>approved_tier</code> of w1_pass, w2_pass, advanced or incubated, and <code>retired</code>. A status change appends an event; the current status is the latest event.</li>
  <li><strong>Who reads them:</strong> research, as seeds and parents and for novelty; the evaluator, to build its <strong>library</strong>; the host agent, to show the owner what exists.</li>
  <li><strong>Library:</strong> the evaluator's own table, pulled from pool events by sequence. An entry becomes effective for correlation and novelty checks once its W1 official record exists. Statuses mirror the pool: seed, active (any approved tier), retired. Library changes are released as <code>library</code> reports.</li>
  <li><strong>Monitoring:</strong> forward simulation keeps running for approved factors and strategies, and the evaluator tracks rolling 60-day s × RankIC_mean. v1 alarm rule: the rolling mean stays below 0 for 20 consecutive days. Phase 8 adds a one-sided CUSUM detector.</li>
  <li><strong>Alerts:</strong> an alarm creates an alert readable through <code>qfr.ops.alerts</code>. The owner may retire the entry with <code>qfr.pool.set_status</code>, which needs an approval record. Retirement is released as a library change.</li>
</ul>

<h3 id="s-10-5"><span class="sn">10.5</span>The owner, the host agent and approval records</h3>
<p>QFR has one human: the <strong>owner</strong>, who sets research direction, operates evaluation and approves promotion. Because one person holds every role, separation of duties comes from three mechanisms instead of from three people:</p>
<ul>
  <li><strong>The host agent is not a research agent</strong> (INV-14). It can submit briefs and read, approve and curate, and nothing else. It cannot publish, run research tools, read research-zone data or touch evaluation runs. The research agents, in turn, have no channel to the host agent or the owner except through deliverables and traces that deterministic code assembles.</li>
  <li><strong>Approval records are explicit and verbatim.</strong> Every pool write and every acceptance decision carries an <code>approval_id</code>. <code>qfr.approval.record</code> requires the owner's confirmation text as the host agent received it, plus the host agent's rationale summary and the exact scope (version ids, pool, tier). The MCP server checks that the confirmation text contains the scope's short code (for example <code>APPROVE J-0042 F-3</code>), which the deliverable report includes so the owner can simply repeat it. Approvals are insert-only in <code>control_db</code>.</li>
  <li><strong>Gates and audit stand in for the second person.</strong> In v1 the owner cannot accept a case with a failed gate. Every MCP call, approval, pool event and acceptance decision is audited and readable back through MCP. Phase 8's override requires a rationale, a 24-hour cooling period and a second confirmation.</li>
</ul>
<div class="table-wrap compact">
<table>
<thead><tr><th>Actor</th><th>Can do</th><th>Cannot do</th></tr></thead>
<tbody>
<tr><td>Owner</td><td>Everything, through the host agent: briefs, steering, approvals, pool curation, protocol and policy versions, epoch rollover, reading all evidence, traces and logs</td><td>Bypass gates in v1; write a pool without an approval record; make research see owner-only numbers (by rule and scan)</td></tr>
<tr><td>Host agent</td><td>Translate, submit, follow, fetch, explain, record approvals verbatim, curate pools on instruction, read logs</td><td>Approve on its own initiative; invent a confirmation; run research tools; publish; alter runs, records or quotas; hold LLM keys</td></tr>
<tr><td>Research agents</td><td>Propose, draft, review, publish within quota, read released reports and pools</td><td>See official records, W3, window dates, owner-only evidence, the host agent, the pools' write routes, evaluation controls</td></tr>
<tr><td>Evaluator</td><td>Measure, release, open cases, sync the library, alert</td><td>Promote, write pools, talk to research except through released reports</td></tr>
</tbody>
</table>
</div>

<h3 id="s-10-6"><span class="sn">10.6</span>Epoch rollover (Phase 8)</h3>
<p>Rollover is manual and owner-approved through <code>qfr.ops.rollover_epoch</code> with an approval record. It happens when W1 or W2 burn meters go red, or once a year.</p>
<ul>
  <li>Create a new epoch id. The new research cutoff is the end of the old W2, so the old W1 and W2 become research-visible.</li>
  <li>The old W3 becomes the new W1, and the new W2 and W3 come from data accumulated since, with embargoes.</li>
  <li>Fingerprint dates are resampled. The trial ledger restarts for each new window.</li>
  <li>The pools and the library are unaffected, old official records stay linked to their epoch, and the blackboard keeps its history tagged by epoch.</li>
  <li>A dry run on the synthetic world <span class="kw">MUST</span> show that every record link and every trace link is preserved.</li>
</ul>
</section>
<!-- ===================================================== CHAPTER 11 -->
<section class="chapter" id="ch-11">
<div class="chapter-kicker"><span class="n">11</span>Chapter 11</div>
<h2>Research system<a class="anchor" href="#ch-11">#</a></h2>

<h3 id="s-11-1"><span class="sn">11.1</span>Programs, charters and research jobs</h3>
<p>A <strong>research job</strong> is the owner's unit of work: one brief in, one or more deliverables out (<a href="#s-13-3">Section 13.3</a>). A <strong>program</strong> is the research zone's long-running effort governed by a <strong>charter</strong>. Every job creates exactly one program, and the charter is derived deterministically from the brief by the research control API: no LLM is involved in turning a brief into a charter. A follow-up job that names a <code>parent_job_id</code> creates a new program whose population and archive are copied from the parent program's final state, so iteration continues rather than restarts.</p>
<p>Charter fields (YAML, versioned on every change, changes apply from the next generation):</p>
<ul>
  <li>Objective in plain language, copied from the brief. Steering notes from <code>qfr.job.steer</code> are appended as dated entries.</li>
  <li>Mode: new_factors, improve_factors, new_strategy, improve_strategy or review_and_iterate, which fixes the operator mix bias and the deliverable kind.</li>
  <li>Seeds: pool entry ids, version ids and brief expressions published as <code>human_seed</code> versions at job start.</li>
  <li>Enabled islands (themes) and optional extra guidance per island. Auto selection maps the brief's mode and seeds to islands (for example "momentum-style" enables I1 and I5 plus I6).</li>
  <li>Budgets: LLM cost per generation and per day, a per-job cap, publications per generation (default 12) and maximum concurrent tasks (default 4).</li>
  <li>Constraints: allowed subsets of fields and operators, and complexity caps no looser than the evaluator's.</li>
  <li>Deliverable criteria: tier, minimum count, maximum candidates, and the stop conditions (maximum generations, wall clock, cost).</li>
  <li>Cadence: the next generation starts as soon as the previous generation's feedback is complete, that is, every version it published has been answered. A version is answered when one of these has been released for it: an intake FAIL, DUPLICATE or DEFERRED report, a screening FAIL, or a W1 report. The seeds published at job start count as generation 0, and a generation or seed set that published nothing is answered at once. If feedback is still incomplete <code>max_wait_hours</code> (default 6) after the previous generation closed, the next generation starts with what has arrived. After a FAILED generation the next one always waits the full <code>max_wait_hours</code>, so a provider outage cannot use up the generation cap in minutes. Generations continue until a stop condition or the deliverable criteria are met; the cost caps (Section 11.7) and the evaluator's quotas (Section 9.3) bound how fast they run.</li>
</ul>

<h3 id="s-11-2"><span class="sn">11.2</span>Agent roster</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Role</th><th>Type</th><th>Default provider / tier</th><th>Inputs</th><th>Output</th><th>Run limits</th></tr></thead>
<tbody>
<tr><td>Supervisor</td><td>LLM plus deterministic validator and fallback</td><td>DeepSeek, strong</td><td>Charter, budget state, island statistics, digests of new reports, evolution proposal, open hypotheses</td><td>GenerationPlan</td><td>1 run per generation, 8 requests at most</td></tr>
<tr><td>Hypothesis researcher</td><td>LLM</td><td>Kimi, strong</td><td>Task brief, island theme, similar existing hypotheses, relevant knowledge items</td><td>1 to 3 Hypothesis objects</td><td>6 requests</td></tr>
<tr><td>Factor engineer</td><td>LLM</td><td>GLM, fast (DeepSeek fast, then Kimi fast, as fallbacks)</td><td>Hypothesis or mutation brief, parent manifests with their released report digests, DSL reference card</td><td>1 to 3 CandidateDraft or StrategyDraft objects</td><td>12 requests, 20 tool calls</td></tr>
<tr><td>Critic</td><td>LLM</td><td>A different provider from the engineer that drafted the candidate; DeepSeek strong by default</td><td>Candidate, hypothesis, workbench summary, most similar factors</td><td>ReviewVerdict</td><td>4 requests</td></tr>
<tr><td>Report analyst</td><td>LLM</td><td>Kimi, strong</td><td>New released reports, their manifests, parent reports</td><td>ReportInterpretation and KnowledgeItem objects</td><td>4 requests</td></tr>
<tr><td>Interpretation reviewer</td><td>LLM (critic prompt in interpretation mode)</td><td>GLM, strong</td><td>Interpretation plus the reports it cites</td><td>InterpretationChallenge</td><td>Samples 30% of interpretations</td></tr>
<tr><td>Evolution engine</td><td>Deterministic code. LLM variation goes through the engineer</td><td>n/a</td><td>Population, fitness, archive, bandit state</td><td>GenerationProposal</td><td>n/a</td></tr>
<tr><td>Packager</td><td>Deterministic code</td><td>n/a</td><td>Approved and selected candidate, its trace</td><td>Manifest, then publication</td><td>n/a</td></tr>
<tr><td>Feedback sync, job monitor, deliverable assembler</td><td>Deterministic code</td><td>n/a</td><td>Feedback API, blackboard, trace</td><td>Cached reports, report links, deliverables, iteration histories</td><td>n/a</td></tr>
</tbody>
</table>
</div>
<p>Provider and model ids per role come from <code>configs/research/roles.yaml</code> and <code>configs/research/providers.yaml</code> (<a href="#s-11-8">Section 11.8</a>). Every provider and model id used is recorded in provenance and in the trace.</p>

<h3 id="s-11-3"><span class="sn">11.3</span>Tools and permission matrix</h3>
<p>Each tool is a typed Python function registered with an allow-list of roles. The tool layer checks the calling role on every invocation, logs the call, and appends a trace step.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Tool</th><th>Purpose</th><th>Supervisor</th><th>Hypothesis</th><th>Engineer</th><th>Critic</th><th>Analyst</th><th>Evolution</th><th>Packager</th></tr></thead>
<tbody>
<tr><td>blackboard.read</td><td>Read entities by id or query</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td></tr>
<tr><td>blackboard.write</td><td>Write the role's own entity types only (see below)</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td></tr>
<tr><td>kb.search</td><td>Search failure modes and insights</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>no</td><td>no</td></tr>
<tr><td>dsl.validate, dsl.explain</td><td>Parse, type-check, constraints, canonical form, deterministic plain-language explanation</td><td>no</td><td>no</td><td>yes</td><td>yes</td><td>no</td><td>yes</td><td>yes</td></tr>
<tr><td>workbench.evaluate</td><td>W0-only metrics using the evaluator's definitions, for factors and composites</td><td>no</td><td>no</td><td>yes</td><td>yes</td><td>no</td><td>yes</td><td>no</td></tr>
<tr><td>similarity.search</td><td>AST and behavioral similarity against pools and population</td><td>no</td><td>yes</td><td>yes</td><td>yes</td><td>no</td><td>yes</td><td>yes</td></tr>
<tr><td>feedback.read</td><td>Released reports, public cards, library</td><td>yes</td><td>no</td><td>yes</td><td>no</td><td>yes</td><td>yes</td><td>no</td></tr>
<tr><td>registry.read</td><td>Manifests of published versions, pools</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td><td>yes</td></tr>
<tr><td>registry.publish</td><td>Publish an artifact version</td><td>no</td><td>no</td><td>no</td><td>no</td><td>no</td><td>no</td><td>yes</td></tr>
<tr><td>budget.read</td><td>Remaining budgets</td><td>yes</td><td>no</td><td>no</td><td>no</td><td>no</td><td>yes</td><td>no</td></tr>
</tbody>
</table>
</div>
<p>Write scopes for blackboard.write:</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Role</th><th>May write</th></tr></thead>
<tbody>
<tr><td>Supervisor</td><td>Plans and task assignments</td></tr>
<tr><td>Hypothesis researcher</td><td>Hypotheses</td></tr>
<tr><td>Engineer</td><td>Candidates and strategy drafts</td></tr>
<tr><td>Critic</td><td>Reviews and interpretation challenges</td></tr>
<tr><td>Analyst</td><td>Interpretations and knowledge items</td></tr>
<tr><td>Evolution engine</td><td>Population, archive and bandit state</td></tr>
<tr><td>Packager</td><td>Publication links and lineage edges</td></tr>
</tbody>
</table>
</div>
<p>There is deliberately no tool that touches evaluation scheduling, protocols, simulations, official records, pools or the owner's jobs, and test BND-02 snapshots the tool registry to prove it. Trace steps are appended by the tool layer and the workflow, never by an agent tool.</p>

<h3 id="s-11-4"><span class="sn">11.4</span>Structured outputs</h3>
<p>All outputs are Pydantic models, and every field is required unless noted.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Model</th><th>Fields</th></tr></thead>
<tbody>
<tr><td>Hypothesis</td><td>title. observation (a generic pattern, never tickers, dates or events). mechanism (why it should persist: risk premium, behavioral bias, liquidity provision, slow information diffusion, and so on). expected_sign. horizon_days. fields_required. falsification. novelty_note relative to the similar hypotheses shown. risks. island_id. tags</td></tr>
<tr><td>CandidateDraft</td><td>hypothesis_id. expression. description (one paragraph mapping each part of the expression to the mechanism). expected_sign. horizon_days. parameter_rationale (why these windows). operator. parent_version_ids. change_summary (when a parent exists)</td></tr>
<tr><td>StrategyDraft</td><td>components (version ids with sign and weight, at most 8). portfolio (top_k, dropout). composition_rationale. expected_horizon_days. parent_version_ids. change_summary (when a parent exists)</td></tr>
<tr><td>ReviewVerdict</td><td>verdict: approve, revise or reject. Scores from 0 to 1: c1 (hypothesis-to-description alignment), c2 (description-to-expression alignment), plausibility, parsimony, originality, and lookahead or snooping risk (higher means riskier). required_changes (mandatory for revise). rationale</td></tr>
<tr><td>ReportInterpretation</td><td>report_ids. what_was_tested. observed (restates only released values). diagnosis (likely causes, labelled as conjecture). implications (hypothesis ids supported or weakened). next_steps (at most 3, concrete). confidence: low, medium or high. caveats (must acknowledge coarsening and multiple testing)</td></tr>
<tr><td>InterpretationChallenge</td><td>interpretation_id. issues (overclaiming, narrative fallacy, ignoring coarsening, regime stories without evidence, and so on). verdict: accept or amend. amended_text (optional)</td></tr>
<tr><td>GenerationPlan</td><td>objectives. allocations: island id to slots, taken from the bandit, adjustable by at most 1 per island with a reason. tasks: type (explore, llm_mutation, crossover, repair, syntactic_batch or compose_strategy), island_id, brief, parent_version_ids, hypothesis_id, max_candidates (3 or fewer). islands_to_pause with reasons. rationale</td></tr>
<tr><td>KnowledgeItem</td><td>kind: failure_mode, insight or anti_pattern. statement. evidence_report_ids. tags</td></tr>
</tbody>
</table>
</div>

<h3 id="s-11-5"><span class="sn">11.5</span>Prompting rules</h3>
<p>These apply to every research prompt. Prompt templates are versioned files under <code>prompts/</code>, and their template id and hash go into provenance and the trace, together with the full rendered prompt.</p>
<ul>
  <li>State the separation explicitly: the agent cannot run official evaluations, released numbers are coarsened, and results must never be invented.</li>
  <li>Never use tickers, company names, specific dates or historical events as justification. Mechanisms must be generic and plausibly persistent. This limits designs driven by memorized history.</li>
  <li>Prefer simple expressions. Justify every window choice. No constant tuning.</li>
  <li>Use workbench.evaluate on W0 to sanity-check ideas, and treat W0 numbers as in-sample and optimistic.</li>
  <li>Return only the output schema, and include uncertainty.</li>
  <li>Provide a DSL reference card (operators, fields, constraints, examples) generated automatically from the operator registry, which is the single source of truth.</li>
  <li>Context assembly, a prompt sampler in the AlphaEvolve style, includes: the owner's objective and steering notes from the charter; parent manifests and their released report digests; the top 3 elites of the island and 2 diverse archive members; relevant knowledge items; and, for improve modes, the seed entries named in the brief.</li>
  <li>Keep each call within a context budget (default 12,000 tokens). Truncate oldest material first.</li>
</ul>

<h3 id="s-11-6"><span class="sn">11.6</span>Generation workflow</h3>
<p>The workflow is a deterministic state machine whose states are PENDING, SYNCING, PROPOSING, PLANNING, DEVELOPING, SELECTING, PUBLISHING and CLOSED. FAILED and ABORTED are terminal. State is persisted after every step, every step is idempotent and resumable, and every transition is a trace step and a log line.</p>
<ol>
  <li><strong>SYNCING:</strong> feedback sync pulls reports released since the program's cursor and stores cached copies and links; the report analyst interprets new W1, W2, simulation and decision reports; the interpretation reviewer challenges a 30% sample; knowledge items are updated, and hypothesis statuses are updated (supported or weakened) from final interpretations. The job monitor checks deliverable criteria against the new reports.</li>
  <li><strong>PROPOSING:</strong> the evolution engine updates fitness, the archive and the bandit, then emits a GenerationProposal with the slot allocation, parent sets, the operator mix and ready-made syntactic candidates.</li>
  <li><strong>PLANNING:</strong> the supervisor writes a GenerationPlan. A deterministic validator enforces: total candidate slots at most 3 times the publication quota; exploration share at least 25%; at least 1 slot for each active island; remaining budget respected. An invalid plan gets one repair attempt, then falls back to the proposal's default plan.</li>
  <li><strong>DEVELOPING:</strong> tasks run in parallel (asyncio, concurrency 4). Explore tasks start with the hypothesis researcher; the factor engineer drafts, using tools; automated checks run (dsl.validate, workbench pre-screen); the critic, on a different provider, reviews. On revise, the engineer revises, for at most 2 review rounds. Approved candidates are stored. Compose_strategy tasks run the engineer in strategy mode over the job's candidate set and the pools.</li>
  <li><strong>SELECTING:</strong> the evolution engine applies the publication pre-screen and dedups against the registry and the population (canonical and behavioral). It then ranks by provisional fitness plus novelty and selects at most the publication quota, with per-island fairness.</li>
  <li><strong>PUBLISHING:</strong> the packager verifies trace completeness, assembles manifests and publishes them, then stores version ids and lineage edges.</li>
  <li><strong>CLOSED:</strong> write a generation summary note, close the cost ledger and emit metrics. The job monitor re-evaluates stop conditions.</li>
</ol>
<p>Failure handling: LLM and tool errors are retried 3 times with exponential backoff, then the role's fallback provider is tried; a failed task never fails the generation; budget exhaustion skips straight to SELECTING with whatever is ready; after a crash, the generation resumes from its last persisted state.</p>

<h3 id="s-11-7"><span class="sn">11.7</span>Budget control</h3>
<ul>
  <li>Every agent run uses PydanticAI usage limits (requests, tool calls, tokens) taken from config, and the provider layer converts usage to cost with the configured price table.</li>
  <li>The budget currency is configuration, default CNY, because all three providers bill their China endpoints in CNY. The ledger enforces the generation cap (default 20 CNY), the daily cap (default 200 CNY) and the job cap from the brief (default 500 CNY). It checks an estimate before each call and the actual usage after it.</li>
  <li>Hitting the daily cap is a hard stop: the generation moves to SELECTING and then CLOSED, and the job waits for the next day. Hitting the job cap closes the job with a best-effort deliverable.</li>
  <li>A role whose model has no price configured <span class="kw">MUST NOT</span> run. The probe in <a href="#s-11-8">Section 11.8</a> catches this at setup.</li>
  <li>Every LLM call is logged with role, provider, model, prompt template id and hash, input and output tokens, cached tokens where the provider reports them, cost at the peak or off-peak rate in force, latency, finish reason, output mode, run id, task id and job id. The full request and response are stored in <code>agent_runs</code>.</li>
  <li>Every call sets <code>max_completion_tokens</code> explicitly, because Moonshot counts that value, not actual output, against its token-per-minute limit.</li>
  <li>Tests run with real model requests disabled and use TestModel or FunctionModel.</li>
</ul>

<h3 id="s-11-8"><span class="sn">11.8</span>LLM providers: Kimi, GLM and DeepSeek</h3>
<p>The research side uses exactly three online providers: <strong>Kimi</strong> (Moonshot AI), <strong>GLM</strong> (Zhipu AI; Z.ai outside China) and <strong>DeepSeek</strong>. All three expose OpenAI-style chat completions with tool calling, so QFR needs one adapter <em>interface</em>. They are not interchangeable in the details, so the adapter carries one <strong>provider profile</strong> per provider: how thinking is switched on and off, whether reasoning text must be echoed back on later turns, which <code>tool_choice</code> values are legal, which structured-output modes exist, how sampling parameters behave, which usage fields report cached tokens, and how rate limits are enforced. PydanticAI ships provider classes that already encode most of these quirks (<code>DeepSeekProvider</code>, <code>MoonshotAIProvider</code>, and <code>ZaiProvider</code> with <code>ZaiModel</code>); QFR builds on them instead of on a bare generic provider, and adds configuration, the probe, budgeting, fallbacks and tracing on top.</p>
<p>QFR sends <strong>text only</strong>: prompts, the DSL reference card, manifests and released-report digests. No image, file or audio ever reaches a provider, so the providers' multimodal and file-upload paths (Kimi's files API, GLM's native vision models, DeepSeek's vision variant) are irrelevant to this system. Attachments the owner supplies stay with the host agent, which turns them into text in the brief.</p>

<div class="callout warn"><span class="ico">!</span><div><b class="t">Verified on 2026-10-30, and expected to drift</b>
<p>The facts in the matrix below were checked against the three providers' documentation and PydanticAI's provider documentation on 2026-10-30. Lineups moved a lot in the preceding twelve months: DeepSeek retired <code>deepseek-chat</code> and <code>deepseek-reasoner</code> on 2026-07-24 in favour of <code>deepseek-flash</code> and <code>deepseek-v4-pro</code>; Moonshot retired the <code>kimi-k2</code> series on 2026-05-25 and <code>kimi-k2.5</code> on 2026-08-31 in favour of <code>kimi-k3</code>, <code>kimi-k3.1-pro</code> and <code>kimi-k2.6</code>; Zhipu's default moved to <code>glm-5.3</code>. Every model id, price and limit is therefore configuration that the probe verifies at setup, daily and at each job start. Nothing in this section may be hard-coded.</p></div></div>

<h4>Compatibility matrix for QFR's use (text, tools, structured output)</h4>
<div class="table-wrap compact matrix">
<table>
<thead><tr><th>Aspect</th><th>DeepSeek</th><th>Kimi (Moonshot)</th><th>GLM (Zhipu / Z.ai)</th><th>What the QFR adapter does</th></tr></thead>
<tbody>
<tr><td>Endpoint</td><td><code>https://api.deepseek.com</code>; strict tool schemas only on <code>https://api.deepseek.com/beta</code></td><td>China <code>https://api.moonshot.cn/v1</code>; international <code>https://api.moonshot.ai/v1</code></td><td>China <code>https://open.bigmodel.cn/api/paas/v4</code>; international <code>https://api.z.ai/api/paas/v4</code></td><td>One base URL and one key variable per provider in providers.yaml. The owner picks the China or international endpoint; prices follow the endpoint</td></tr>
<tr><td>Models offered today (examples, not fixed)</td><td><code>deepseek-flash</code> (V4.1-Flash, 1M context, up to 384K output), <code>deepseek-v4-pro</code> (V4-Pro-0813, 1M context). Both have thinking and non-thinking modes. A routing of v4-pro requests to Flash was announced for after 2026-09-14; the pricing page still lists both</td><td><code>kimi-k3.1-pro</code> (1M context, flagship), <code>kimi-k3</code> (1M context), <code>kimi-k2.6</code> (256K context, thinking optional), <code>kimi-k2.7</code> (coding model, always thinks)</td><td><code>glm-5.3</code> (default), <code>glm-5.3-flash</code>, <code>glm-5.3-flashx</code>, <code>glm-5.2</code>, <code>glm-5.1</code>, <code>glm-5</code>, <code>glm-4.7</code>, <code>glm-4.6</code>; 200K context, up to 128K output</td><td>Ids live in providers.yaml. The probe lists the provider's models and refuses an id that is absent</td></tr>
<tr><td>Thinking control</td><td><code>thinking: {type: enabled | disabled}</code> (default enabled) and <code>reasoning_effort: none | low | high | max</code> (default high; none disables). Temperature has no effect in thinking mode</td><td><code>kimi-k3</code> always thinks; effort via top-level <code>reasoning_effort: low | high | max</code> (default max). <code>kimi-k2.6</code> accepts <code>thinking: {type: ...}</code>. <code>kimi-k2.7</code> always thinks with no effort control</td><td><code>thinking: {type: enabled | disabled}</code>, default enabled. <code>glm-5.3</code>, <code>glm-5.3-flash</code> and <code>glm-4.7</code> cannot disable thinking; <code>glm-5.2</code>, <code>5.1</code>, <code>5</code> and <code>4.6</code> decide per request. <code>glm-5.2</code> and <code>5.3</code> also accept an effort level</td><td>Roles declare <code>thinking: on | off</code> and an effort. PydanticAI's unified thinking setting maps it per provider (for example off on <code>kimi-k3</code> becomes low effort). The probe records which switch each model honours</td></tr>
<tr><td>Reasoning text on later turns</td><td>If the request carries <code>tools</code>, the <code>reasoning_content</code> of every earlier assistant turn must be sent back, even on turns without tool calls, or the API returns 400. Without tools it need not be sent</td><td>The service manages reasoning fields across multi-step tool calls; the prior thinking content is included in the input as returned</td><td>Preserved thinking is the default (<code>clear_thinking: false</code>): <code>reasoning_content</code> must be returned complete and unmodified in sequence. <code>clear_thinking: true</code> opts out</td><td>PydanticAI sends thinking parts back in each provider's expected format (<code>openai_chat_send_back_thinking_parts: auto</code>; <code>ZaiModel</code> preserved thinking). QFR stores the reasoning text in <code>agent_runs</code> for the trace and never forwards it to another agent</td></tr>
<tr><td><code>tool_choice</code></td><td><code>none</code>, <code>auto</code>, <code>required</code> and a named function; <code>required</code> and named return 400 in thinking mode</td><td><code>auto</code>, <code>none</code>, <code>required</code> and a named function</td><td><code>auto</code> only; forced choices are not supported</td><td>QFR never forces a tool choice. Profiles set <code>openai_supports_tool_choice_required</code> false for GLM and <code>openai_supports_forced_tool_choice_with_thinking</code> false for DeepSeek</td></tr>
<tr><td>Strict tool schemas</td><td>Beta endpoint only, <code>strict: true</code>, every property required, <code>additionalProperties: false</code></td><td>Not documented</td><td>Not supported (<code>openai_supports_strict_tool_definition</code> false)</td><td>Strict mode off everywhere. PydanticAI validates tool arguments against the Pydantic model and retries on failure</td></tr>
<tr><td>JSON output modes</td><td>Chat completions: <code>response_format: {type: json_object}</code>, the word "json" must appear in the prompt, set <code>max_tokens</code>, occasional empty content. <code>json_schema</code> only on the separate Responses API</td><td><code>json_object</code> and <code>json_schema</code>; Moonshot recommends <code>json_schema</code> for structured output and requires the fields to be described in the prompt for <code>json_object</code></td><td><code>json_object</code> only; schema validation is the client's job</td><td>Structured output uses tool calling with <code>tool_choice: auto</code> everywhere (PydanticAI ToolOutput). Fallback after two validation failures in one run: PromptedOutput with <code>json_object</code>. Native JSON-schema output is not used because only Kimi offers it on chat completions</td></tr>
<tr><td>Sampling parameters</td><td>Temperature ignored in thinking mode; honoured in non-thinking mode</td><td>Kimi K2 models recommended 0.6 (the Anthropic-compatible endpoint scales temperature by 0.6); K2.5 thinking fixed temperature at 1.0; K3 behaviour not documented</td><td><code>do_sample</code> default true; temperature range 0 to 1 (China docs: 0 exclusive), default 1.0 on GLM-5 and 4.7; <code>top_p</code> 0.01 to 1, default 0.95; set only one of the two</td><td>Role temperatures apply to non-thinking calls only; thinking calls run at provider defaults. Temperatures are clamped to each provider's range by the profile and the probe logs what was accepted</td></tr>
<tr><td>Usage and caching fields</td><td>Automatic prefix cache; usage reports <code>prompt_cache_hit_tokens</code> and <code>prompt_cache_miss_tokens</code></td><td>Automatic prefix cache, 5-minute default TTL (1-hour option), cache hit priced at one tenth of a miss, cache-write fee on <code>kimi-k3</code>; usage reports cached tokens</td><td>Cached input priced separately; usage reports cached tokens in the prompt-token details</td><td>Cost = Σ price × tokens per class (miss, hit, write, output). A class the provider does not report is billed as a miss, so estimates err high</td></tr>
<tr><td>Rate limits</td><td>Per-account concurrency: 2,500 on <code>deepseek-flash</code>, 500 on <code>deepseek-v4-pro</code>; 429 beyond that</td><td>Concurrency, RPM, TPM and TPD per account, shared across all models, raised by cumulative top-up tier. Tier 0 is tiny: default SDK retries alone can exhaust its RPM. TPM counts the request's <code>max_completion_tokens</code>, not actual output</td><td>Per-model concurrency caps by user tier V0 to V3 (for example 50 to 500 on older models); 429 with code 1302; increases by application</td><td>Global concurrency 4. <code>max_completion_tokens</code> set on every call (4,096 for drafts and reviews, 16,384 for plans and interpretations). 429 → backoff, then the fallback chain. Setup refuses to finish until the Moonshot tier allows the configured concurrency</td></tr>
<tr><td>Timeouts and keep-alive</td><td>Non-streaming requests receive blank keep-alive lines; the server closes the connection if inference has not started within 10 minutes</td><td>Standard</td><td>Standard</td><td>Non-streaming calls with a 120 s timeout for fast roles and 600 s for thinking roles; the OpenAI SDK tolerates the blank lines</td></tr>
<tr><td>Pricing and currency (China endpoints, per 1M tokens, as published on 2026-10-30)</td><td>Peak and off-peak prices; off-peak is half price. Peak is 01:00–04:00 and 06:00–10:00 UTC, Monday to Friday, excluding Chinese public holidays. Flash about 0.3 USD in (miss), 1.2 USD out at peak; V4-Pro about 1.32 USD in, 3.96 USD out at peak</td><td><code>kimi-k3.1-pro</code>: 13 CNY in (miss), 1.3 CNY cache hit, 68 CNY out. <code>kimi-k3</code>: 20 CNY in, 2 CNY cache hit, 100 CNY out. International list in USD (K3.1 Pro 2 in, 10 out)</td><td><code>glm-5.3</code>: 8 CNY in, 2 CNY cache hit, 28 CNY out. <code>glm-5.3-flash</code>: 0.8 CNY in, 0.23 CNY cache hit, 2.8 CNY out (a limited-time half-price offer was listed)</td><td>Price table per model with peak and off-peak columns where the provider has them. Budgets in CNY; USD prices are converted with a configured rate. A model without a price refuses to run</td></tr>
<tr><td>Multimodal and files</td><td>Vision variant and Responses API exist</td><td>Files API, vision on K3.1 Pro and K2.6</td><td>Native vision on the 5.3-Flash family</td><td>Not used. QFR is text only</td></tr>
</tbody>
</table>
</div>

<pre><code># configs/research/providers.yaml (keys are referenced by environment variable name only;
# every id and price below is an example to verify at setup, not a fact to rely on)
providers:
  deepseek:
    base_url: https://api.deepseek.com
    api_key_env: DEEPSEEK_API_KEY
    pydantic_ai_provider: deepseek
    models:
      deepseek-v4-pro: {tier: strong, thinking: on,  effort: high, price_cny_per_mtok: {in_miss: null, in_hit: null, out: null, offpeak_factor: 0.5}}
      deepseek-flash:  {tier: fast,   thinking: off,               price_cny_per_mtok: {in_miss: null, in_hit: null, out: null, offpeak_factor: 0.5}}
  kimi:
    base_url: https://api.moonshot.cn/v1          # international: https://api.moonshot.ai/v1
    api_key_env: MOONSHOT_API_KEY
    pydantic_ai_provider: moonshotai
    models:
      kimi-k3:   {tier: strong, thinking: always, effort: high, price_cny_per_mtok: {in_miss: null, in_hit: null, cache_write: null, out: null}}
      kimi-k2.6: {tier: fast,   thinking: off,                  price_cny_per_mtok: {in_miss: null, in_hit: null, out: null}}
  glm:
    base_url: https://open.bigmodel.cn/api/paas/v4   # international: https://api.z.ai/api/paas/v4
    api_key_env: ZHIPU_API_KEY
    pydantic_ai_provider: zai
    models:
      glm-5.3:       {tier: strong, thinking: always, effort: high, price_cny_per_mtok: {in_miss: null, in_hit: null, out: null}}
      glm-5.3-flash: {tier: fast,   thinking: always,               price_cny_per_mtok: {in_miss: null, in_hit: null, out: null}}
request:
  concurrency: 4
  timeout_s: {fast: 120, thinking: 600}
  retries: 3
  backoff_s: [2, 8, 30]
  max_completion_tokens: {draft: 4096, review: 4096, plan: 16384, interpretation: 16384}
  structured_output: {primary: tool, fallback: prompted_json_object, fallback_after_failures: 2}
budget:
  currency: CNY
  usd_to_cny: null                                  # set at setup when any provider is billed in USD
  generation_cap: 20
  daily_cap: 200
  job_cap_default: 500
probe:
  run_at: [setup, daily, job_start]

# configs/research/roles.yaml
roles:
  supervisor:    {primary: deepseek/deepseek-v4-pro, fallbacks: [kimi/kimi-k3, glm/glm-5.3],           temperature: 0.2}
  hypothesis:    {primary: kimi/kimi-k3,             fallbacks: [glm/glm-5.3, deepseek/deepseek-v4-pro], temperature: 0.7}
  engineer:      {primary: glm/glm-5.3-flash,        fallbacks: [deepseek/deepseek-flash, kimi/kimi-k2.6], temperature: 0.2}
  critic:        {primary: deepseek/deepseek-v4-pro, fallbacks: [kimi/kimi-k3],                          temperature: 0.2, must_differ_from: engineer}
  analyst:       {primary: kimi/kimi-k3,             fallbacks: [glm/glm-5.3],                           temperature: 0.2}
  interp_review: {primary: glm/glm-5.3,              fallbacks: [deepseek/deepseek-v4-pro],              temperature: 0.2}</code></pre>

<p>Rules of the provider layer:</p>
<ul>
  <li><strong>Provider classes, not a bare client.</strong> The adapter instantiates PydanticAI's <code>DeepSeekProvider</code>, <code>MoonshotAIProvider</code> and <code>ZaiProvider</code> (with <code>ZaiModel</code>) with the configured base URL and key, so each provider's thinking, reasoning pass-back and tool-choice rules are applied by the library. QFR overrides a profile only through configuration, never by patching the library.</li>
  <li><strong>Structured outputs.</strong> Primary mode is tool calling with <code>tool_choice: auto</code> on every provider. After two validation failures inside one run, the run retries in prompted mode with <code>response_format: json_object</code> and the schema in the prompt. The mode actually used is recorded in the trace.</li>
  <li><strong>Thinking policy.</strong> Strong roles run with thinking on at high effort; fast roles run with thinking off where the model allows it. On models that cannot disable thinking (<code>kimi-k3</code>, <code>glm-5.3</code>, <code>glm-5.3-flash</code>, <code>glm-4.7</code>) the role runs at low effort instead, and the extra reasoning tokens are simply priced. Reasoning text is stored in the agent run and never shown to another agent or released.</li>
  <li><strong>Fallback chains.</strong> On timeout, 429 or 5xx after the configured retries, or on a model-not-found error, the role moves to the next provider in its chain. The switch is logged and traced, and the provenance records the model that actually answered.</li>
  <li><strong>Cross-provider review.</strong> The critic that reviews a candidate <span class="kw">MUST</span> use a different provider from the engineer that drafted it (<code>must_differ_from</code>).</li>
  <li><strong>Diversity by default.</strong> The default mapping spreads roles across all three providers so that no single provider's style dominates the population and no single outage stops research.</li>
  <li><strong>Probe.</strong> <code>qfr llm probe</code> (also behind <code>qfr.setup.status</code>) runs at setup, daily and at every job start. For each configured model it lists the provider's models and checks the id exists, sends one small text request with a tool definition and one with <code>json_object</code>, exercises the configured thinking switch, verifies that a price is configured, and on Moonshot reads the account tier against the configured concurrency. Failures raise alerts, and a job does not start on a role whose primary and fallbacks all fail.</li>
  <li><strong>Lifecycle.</strong> Providers retire models within months. Replacing a model is a <code>providers.yaml</code> and <code>roles.yaml</code> change plus a probe run; no code changes and no redeploy of anything but research-worker.</li>
  <li><strong>Cost awareness.</strong> DeepSeek halves prices off-peak. Generations start whenever the previous generation's feedback is complete, so they fall at any hour, and DeepSeek calls made during the weekday peak windows cost twice as much. QFR does not schedule around peak prices on its own; the generation, daily and job caps bound the cost either way.</li>
  <li><strong>Secrets.</strong> Keys are read from the environment of research-worker only, never logged, never included in traces or exports, and scrubbed by the logging redaction processor if they ever appear in a message.</li>
  <li><strong>Tests.</strong> The test suite never calls a provider. FunctionModel scenarios script every role. The manual, owner-authorized smoke run exercises each real provider once per phase that changes the provider layer.</li>
</ul>
</section>

<!-- ===================================================== CHAPTER 12 -->
<section class="chapter" id="ch-12">
<div class="chapter-kicker"><span class="n">12</span>Chapter 12</div>
<h2>Evolutionary engine<a class="anchor" href="#ch-12">#</a></h2>

<h3 id="s-12-1"><span class="sn">12.1</span>Population structure</h3>
<ul>
  <li><strong>Islands:</strong> 6 themes by default. Each island holds up to 60 members. I1 momentum and trend; I2 reversal and mean reversion; I3 volatility and risk; I4 liquidity and volume; I5 price–volume interaction; I6 open exploration. A job's mode and seeds select which islands are active.</li>
  <li>A member is either <strong>official</strong> (a published version with at least one released W1 report) or <strong>provisional</strong> (an approved but unpublished candidate with W0 statistics). A provisional member may parent at most 1 child per generation. An unpublished provisional member expires after 3 generations. A published one (a human_seed, or a candidate whose version is waiting for evaluation, including a quota deferral) does not expire: it becomes official when its W1 report arrives, or leaves the population when it is rejected.</li>
  <li><strong>Initialization from the pools.</strong> At program start, pool entries named in the brief, and all pool entries when the mode is improve_factors or improve_strategy, are inserted as official members (they are published versions with W1 records) in the island whose theme matches their tags, or in I6 when untagged. Brief expressions are published as <code>human_seed</code> versions and enter as provisional members until their W1 report arrives.</li>
  <li><strong>Empty start.</strong> When the pools are empty and the brief has no seeds, every island starts empty, the first generation is 100% explore, and the library-correlation terms in fitness are neutral. This is the normal state of a fresh deployment and <span class="kw">MUST</span> work without any special casing beyond these rules (test SET-01).</li>
  <li><strong>Global MAP-Elites archive:</strong> 64 cells, each keeping its best official elite. The cell descriptors are: horizon bucket (the best decay horizon among 1, 5, 10 and 20); turnover bucket (below 0.2, 0.2 to 0.4, 0.4 to 0.6, 0.6 and above); field group (price only, volume only, price and volume, range or volatility).</li>
</ul>

<h3 id="s-12-2"><span class="sn">12.2</span>Fitness</h3>
<p>Official fitness uses released W1 values, which are already coarsened. pct(·) is the percentile rank among official members of the same island. If an island has fewer than 5 official members, global percentiles are used instead.</p>
<pre><code>F = 0.40·pct(RankIC_IR) + 0.25·pct(LS net Sharpe) + 0.15·pct(1 − max library corr)
  + 0.10·pct(monotonicity) + 0.10·pct(1 − top turnover) − 0.01·max(0, nodes − 15)</code></pre>
<ul>
  <li>Multipliers: 0 if screening failed or SIGN_MISMATCH was flagged; 1.1 after a W2 PASS; 0.5 after a W2 FAIL.</li>
  <li>When the library is empty, pct(1 − max library corr) is defined as 0.5 for every member.</li>
  <li>An approved pool entry remains a valid parent, but its descendants must pass novelty checks against the library.</li>
  <li>Coarsening produces ties. They are broken by originality, then by lower complexity.</li>
  <li>Provisional fitness uses the same formula on W0 workbench metrics, multiplied by 0.5. It is used only to choose which candidates to publish, and never enters the archive.</li>
</ul>

<h3 id="s-12-3"><span class="sn">12.3</span>Selection</h3>
<ul>
  <li>For each slot: with probability 0.7, exploit, using a tournament of size 3 among the island's top 10 by fitness. With probability 0.3, explore: pick a uniformly random archive cell from any island and take its elite.</li>
  <li>Crossover pairs one parent from the island with a second parent from another island or archive cell, with behavioral similarity of 0.5 or less.</li>
</ul>

<h3 id="s-12-4"><span class="sn">12.4</span>Variation operators and default mix</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Operator</th><th>Share</th><th>Mechanism</th></tr></thead>
<tbody>
<tr><td>explore</td><td>25%</td><td>New hypothesis from the hypothesis researcher, implemented by the engineer</td></tr>
<tr><td>llm_mutation</td><td>35%</td><td>Targeted revision of the parent's weakest decision, in the style of QuantaAlpha trajectory mutation. The engineer gets the parent, its report digest, its flags and a targeted instruction. HIGH_TURNOVER: smooth, or lengthen windows. CROWDED_WITH_LIBRARY: orthogonalize, or add novel conditioning. DECAYS_FAST: change horizon. SIGN_MISMATCH: revisit the mechanism, never just flip the sign</td></tr>
<tr><td>crossover</td><td>15%</td><td>The engineer merges two parents' mechanisms into one coherent expression with a merged rationale. When the LLM budget is low, deterministic subtree exchange is used instead</td></tr>
<tr><td>syntactic_mutation</td><td>20%</td><td>Deterministic, no LLM. Window jitter of one step within the allowed set. Operator swap within a class (Mean, EMA, WMA, Med; Std, Var, max minus min). Wrapping with Rank, TsZ or EMA. Replacing a subtree with a random depth-2 subtree. Field substitution within a group (close and vwap)</td></tr>
<tr><td>repair</td><td>5%</td><td>Fix screening failures (LOW_COVERAGE, DEGENERATE) of promising hypotheses</td></tr>
</tbody>
</table>
</div>
<p>Mode bias: improve modes raise llm_mutation to 45% and lower explore to 15%; strategy modes add compose_strategy tasks (deterministic candidate-set assembly plus the engineer in strategy mode) outside this mix, at most 2 per generation. Syntactic mutants get an auto-generated change summary, inherit the parent's rationale, and count as trials like any other version. Every operator application, including syntactic ones, is a trace step with the AST diff.</p>

<h3 id="s-12-5"><span class="sn">12.5</span>Inner loop and outer loop</h3>
<ul>
  <li>The inner loop is free apart from LLM and compute cost. Engineers iterate on W0 through the workbench inside a task, and most of the search happens here.</li>
  <li>Publication pre-screen thresholds: W0 coverage of at least 0.85; s × RankIC_mean on W0 of at least 0.015, and RankIC_IR on W0 of at least 0.10; maximum behavioral similarity to population and pools of 0.90 or less; AST originality of at least 0.2; complexity within caps. Strategies: W0 composite net Sharpe of at least 0.8 and at most 8 components.</li>
  <li>The outer loop is rationed. Only the best 12 or fewer candidates per generation are published, so the official evaluation budget and the trial counts grow slowly.</li>
</ul>

<h3 id="s-12-6"><span class="sn">12.6</span>Budget allocation across islands</h3>
<ul>
  <li>Each island has a Beta-Bernoulli Thompson-sampling arm. Success means a published child whose official fitness is at or above the island's 75th percentile when its report arrives.</li>
  <li>The posterior is Beta(1 + successes, 1 + failures), with exponential forgetting (factor 0.95 per generation).</li>
  <li>Publication slots are split in proportion to sampled values, with a floor of 1 slot per active island and a cap of 40% per island.</li>
  <li>Stagnation: if an island's best fitness has not improved for 8 generations, the supervisor must either reseed it with at least 2 explore tasks or pause it, and the choice is logged and traced.</li>
  <li>Migration: every 5 generations, each island's best member is copied into the next island in a ring, as a parent candidate.</li>
  <li>Diversity guardrails: the exploration share rises to 40% for the next generation when archive coverage drops below 25% of cells or mean behavioral similarity among the top 20 members exceeds 0.6.</li>
</ul>

<h3 id="s-12-7"><span class="sn">12.7</span>Lineage and trajectories</h3>
<ul>
  <li>Lineage edges link each child version to its parent versions, with a relation (mutation, crossover, revision, composition or inspiration), operator details and the AST diff.</li>
  <li>Full trajectories can be queried: brief, hypothesis, candidate, version, released reports, interpretations and children. The development trace (<a href="#ch-14">Section 14</a>) is the step-level record underneath these edges.</li>
  <li>Prompts use trajectories to answer "what has already been tried in this lineage", so the system does not repeat failed attempts, and deliverables use them to generate the iteration history.</li>
</ul>
</section>
<!-- ===================================================== CHAPTER 13 -->
<section class="chapter" id="ch-13">
<div class="chapter-kicker"><span class="n">13</span>Chapter 13</div>
<h2>MCP front door: the owner's control surface<a class="anchor" href="#ch-13">#</a></h2>
<p class="lead">QFR has exactly one human-facing surface: a standard Model Context Protocol server named <code>qfr-mcp</code>. A host agent, whatever vendor it comes from, connects to it the same way it connects to any other MCP server, and from then on the owner's words become QFR's inputs and QFR's results become the owner's reports.</p>

<h3 id="s-13-1"><span class="sn">13.1</span>Role and principles</h3>
<ul>
  <li><strong>Standard, not bespoke.</strong> The server speaks plain MCP: tools with JSON Schema inputs and structured outputs, resources with URIs, and prompts. No client-specific extensions. Claude Code, Codex and any other compliant client work unchanged.</li>
  <li><strong>Owner-grade, not research-grade.</strong> The front door sees what the owner may see, including official records, gate values and W3, and can do what the owner may do. It cannot do what research does (INV-14) and it cannot do what the evaluator does.</li>
  <li><strong>Composer, not a fourth engine.</strong> The server holds no business logic of its own beyond validation, composition and audit. Jobs live in research_db, evidence in eval_db, pools in registry_db. The server owns only approvals, deliveries, setup state and its call audit in <code>control_db</code>.</li>
  <li><strong>Everything through it is logged and audited.</strong> Every call writes a <code>mcp_calls</code> row (principal, tool, argument digest, result size, duration, outcome) and a log line with a request id that propagates to every downstream service.</li>
  <li><strong>Reads are free, writes are explicit, approvals are verbatim.</strong> Read tools can be called at will. Write tools change state and are audited. Approval-gated tools require an approval record that quotes the owner.</li>
</ul>

<h3 id="s-13-2"><span class="sn">13.2</span>Transport, authentication and audit</h3>
<ul>
  <li><strong>Transport:</strong> MCP streamable HTTP, served by the <code>qfr-mcp</code> container and published only on the Mac's loopback interface, default <code>127.0.0.1:8765</code>, path <code>/mcp</code>. Nothing else on the Mac's network stack is exposed. A host agent that only speaks stdio uses the thin launcher <code>qfr-mcp-stdio</code>, which runs on the Mac and forwards to the HTTP endpoint.</li>
  <li><strong>Authentication:</strong> one static bearer token for the owner, <code>QFR_MCP_TOKEN</code>, generated at setup and printed once. The server rejects calls without it. Rotating the token is <code>just rotate-mcp-token</code>. Phase 8 <span class="kw">MAY</span> add OAuth for remote clients, but v1 is loopback only.</li>
  <li><strong>Client configuration:</strong> <code>just mcp-config</code> prints ready-to-paste snippets for Claude Code (<code>claude mcp add</code> with the HTTP transport and the Authorization header) and for Codex (an <code>mcp_servers</code> entry in its configuration), plus a generic JSON block. The exact client syntax is the client's business; the server exposes URL and token and nothing else.</li>
  <li><strong>Limits:</strong> request body 1 MB; long-poll tools wait at most 600 seconds; log and list tools return at most 2,000 items per call with cursors; one concurrent approval-gated write at a time.</li>
  <li><strong>Audit:</strong> the <code>mcp_calls</code> table and the logs volume. The host agent can read its own audit trail with <code>qfr.logs.search(service=qfr-mcp)</code>.</li>
</ul>

<h3 id="s-13-3"><span class="sn">13.3</span>Research briefs and jobs</h3>
<p>The host agent's main job is to turn the owner's intent into a <strong>ResearchBrief</strong>. The brief is a Pydantic model (<code>brief/1</code>) and the <code>qfr.brief</code> prompt explains to the host agent how to fill it. The server validates it, scans it for owner-only numbers (<a href="#s-9-6">Section 9.6</a>), derives a charter deterministically and starts a program.</p>
<pre><code>ResearchBrief (schema brief/1)
  title                 ≤ 120 chars
  objective             ≤ 2,000 chars, the owner's intent in plain language
  mode                  new_factors | improve_factors | new_strategy | improve_strategy | review_and_iterate
  seeds
    pool_entry_ids[]    factors or strategies from the pools to improve or build on
    version_ids[]       any published versions
    expressions[]       {name, expression, expected_sign, horizon_days, rationale}  extracted by the host agent,
                        validated with qfr.dsl.validate, published as human_seed versions at job start
    notes               ≤ 8,000 chars, for example a methodology summary from the owner's attachment
  islands               auto | [I1..I6]
  constraints           fields_allowed[], operators_allowed[], max_nodes, max_lookback_days   (never looser than the evaluator)
  strategy_spec         for strategy modes: {top_k 20..100, dropout 1..20, max_components ≤ 8}
  deliverable
    tier                w1_pass (default) | w2_pass | advanced | incubated
    min_count           default 1
    max_candidates      default 3
  budget
    max_cost            default 500 CNY
    max_generations     default 10
    max_wall_clock_days default 14
  parent_job_id         optional, continue from a previous job's population
  priority              normal | low</code></pre>
<p>Job states, all persisted in research_db and visible through <code>qfr.job.get</code> and <code>qfr.job.events</code>:</p>
<div class="flow">
  <div class="st">SUBMITTED</div><span class="arrow">→</span>
  <div class="st">VALIDATED<small>schema, scan, seeds published</small></div><span class="arrow">→</span>
  <div class="st good">RUNNING<small>generations on the cadence</small></div><span class="arrow">→</span>
  <div class="st wait">WAITING_FOR_EVALUATION<small>generation cap reached, reports pending</small></div><span class="arrow">→</span>
  <div class="st good">DELIVERABLE_READY<small>criteria met</small></div><span class="arrow">→</span>
  <div class="st">DELIVERED<small>host agent fetched it</small></div><span class="arrow">→</span>
  <div class="st owner">CLOSED<small>approved · rejected · expired · cancelled · budget_exhausted</small></div>
</div>
<ul>
  <li>The response to <code>qfr.job.submit</code> states the job id, the derived charter, the seed version ids, and a <strong>timeline estimate</strong> computed from the tier, the evaluator's queue and the quotas: for example "first W1 reports within minutes of the first publication; first deliverable typically within a day" for <code>w1_pass</code>, "typically a few days" for <code>w2_pass</code>, "typically about a week" for <code>advanced</code>, "about one quarter (60 trading days of forward incubation)" for <code>incubated</code>.</li>
  <li>A job can produce several deliverables over time; the job closes when <code>min_count</code> is met and no better candidate is pending, or when a stop condition fires. A stop on budget or generations with nothing meeting the tier closes the job with a <code>best_effort</code> deliverable containing the best candidates so far, clearly labelled.</li>
  <li><code>qfr.job.steer</code> appends owner guidance to the charter for the next generation. <code>qfr.job.pause</code> stops new generations and spending; evaluation of already-published versions continues regardless, because research cannot stop the evaluator and neither can the host agent.</li>
  <li>The owner's third example, "based on the attachment, review the methodology, factors and strategies, and use QFR to iterate them", is mode <code>review_and_iterate</code>: the host agent summarizes the methodology into <code>notes</code>, extracts factors as DSL <code>expressions</code>, describes the strategy as a <code>strategy_spec</code>, and QFR seeds the population with them and iterates.</li>
</ul>

<h3 id="s-13-4"><span class="sn">13.4</span>Deliverables</h3>
<p>A deliverable (<code>deliverable/1</code>) is assembled by deterministic code in the research zone and completed by the front door with owner-grade evidence from the evaluator. The host agent receives it from <code>qfr.deliverable.get</code> and can write a bundle to <code>exports/</code> with <code>qfr.deliverable.export</code>.</p>
<pre><code>Deliverable (schema deliverable/1)
  deliverable_id, job_id, created_at, status: complete | best_effort
  items[]
    version_id, kind, manifest, expression or strategy spec
    tier_reached                   w1_pass | w2_pass | advanced | incubated   (as of created_at)
    iteration_history              iteration_history/1, generated from the trace (Section 14.4)
    trace_ref                      candidate id and trace export hash
    released_reports[]             what research saw
    owner_evidence                 official records on every evaluated window, gate values,
                                   reference-strategy stats, NAV and IC series refs, simulation state
                                   (visibility: owner_only)
    caveats[]                      mandatory, generated: evidence tier, coarsening, trials counted
                                   in this family and program, N_eff, in-sample versus out-of-sample,
                                   LLM memorization warning, cost model limits
  summary                          deterministic text: what was asked, what was delivered, what it cost
  costs                            CNY total, tokens by provider and role, generations run, trials counted
  short_codes                      e.g. J-0042 F-1, J-0042 F-2, used in approval confirmations</code></pre>
<p>Rules:</p>
<ul>
  <li>Backtesting results in a deliverable are the evaluator's, never research-side numbers. Research-side W0 statistics appear only inside the iteration history, labelled in-sample.</li>
  <li>The summary and the caveats are generated by templates from structured data. No LLM writes any part of a deliverable. The host agent may paraphrase for the owner, but the <code>qfr.report_deliverable</code> prompt instructs it to keep the tier, the caveats and the short codes verbatim.</li>
  <li>An export bundle contains <code>deliverable.json</code>, <code>iteration_history.md</code>, <code>trace.json</code>, the manifests, and <code>series/*.parquet</code> plus CSV copies (NAV, daily RankIC, LS returns) for each window, with a <code>MANIFEST.sha256</code>. Bundles are written under <code>exports/&lt;job_id&gt;/&lt;deliverable_id&gt;/</code> on the Mac, where the owner can open them directly.</li>
</ul>

<h3 id="s-13-5"><span class="sn">13.5</span>Approvals and pool curation</h3>
<p>Approval records are the system's record of the owner's decisions. They are created only through <code>qfr.approval.record</code> and are insert-only in <code>control_db</code>.</p>
<pre><code>ApprovalRecord (schema approval/1)
  approval_id, created_at
  decision            approve | reject | retire | accept_case | reject_case | rollover_epoch
  scope               {job_id?, deliverable_id?, version_ids[], pool?, tier?, case_id?, entry_ids[]}
  owner_confirmation  the owner's words as received by the host agent, verbatim, ≤ 2,000 chars
  rationale           the host agent's one-paragraph summary of why, as discussed with the owner
  short_codes_matched the short codes found in owner_confirmation (must cover the scope)
  principal           the MCP token id
  request_id</code></pre>
<ul>
  <li>The server accepts an approval only if <code>owner_confirmation</code> contains the short code of every item in scope (for example <code>APPROVE J-0042 F-1 F-2</code>). The deliverable report carries these codes so the owner can repeat them. This is a guard against the host agent approving on the owner's behalf by paraphrase; it is not cryptographic and does not pretend to be.</li>
  <li><code>qfr.pool.add</code> writes a pool entry for an approved version with the tier reached at approval time. <code>qfr.pool.set_status</code> appends a status event (for example retire) and needs an approval record of the matching decision. <code>qfr.pool.annotate</code> appends tags and notes and needs no approval because it changes no status.</li>
  <li>Rejecting a deliverable (<code>qfr.job.close</code> with decision reject and an approval record) records why, and the host agent may open a follow-up job with <code>parent_job_id</code> and the owner's feedback as steering.</li>
  <li>Acceptance cases opened by the evaluator after incubation are decided with <code>qfr.acceptance.decide</code>, which also needs an approval record. In v1 the decision cannot contradict a failed gate.</li>
  <li>All of these tools are the only way the pools and acceptance cases change. There is no CLI shortcut and no direct SQL path in the runbook (test POOL-01).</li>
</ul>

<h3 id="s-13-6"><span class="sn">13.6</span>Setup and the raw factor pool</h3>
<p>Setup is the only time QFR asks the owner for content. It runs as <code>just setup</code> on the Mac or conversationally through <code>qfr.setup.status</code> and <code>qfr.pool.import</code>, and it asks four questions:</p>
<ol>
  <li><strong>Do you have a raw factor pool to import?</strong> If yes, the owner places a file under <code>imports/</code> and names it. If no, the pools stay empty, and setup prints: "No default factors. No default strategies. Research will start from exploration only. Library-correlation and novelty checks are vacuous until the pool has entries." That state is recorded in <code>setup_state</code> and shown in <code>qfr.status</code>.</li>
  <li><strong>Which providers are configured?</strong> Setup runs <code>qfr llm probe</code> and refuses to finish while any role's primary model is missing from the provider's model list, lacks a price, rejects the configured thinking or output mode, or, on Moonshot, sits on an account tier that cannot serve the configured concurrency.</li>
  <li><strong>Which data source?</strong> synthetic (for a dry run) or cn (downloads the release and builds both snapshots).</li>
  <li><strong>Generate the owner token and print the host-agent configuration.</strong></li>
</ol>
<p>Raw factor pool file format (<code>pool_import/1</code>, JSON, YAML or CSV with the same columns):</p>
<pre><code>entries:
  - name: ma_cross_20_60              # slug, unique
    title: "20/60 moving-average crossover"
    expression: "Mean($close, 20) / Mean($close, 60) - 1"
    expected_sign: 1
    horizon_days: 5
    tags: [momentum, trend]
    notes: "from the owner's 2024 notebook"   # optional
    strategy: null                            # optional strategy/1 spec referencing entries by name</code></pre>
<ul>
  <li>Every expression is parsed, type-checked and constrained exactly like an agent's draft. Invalid entries are reported with reason codes and skipped; the import never partially applies an entry.</li>
  <li>Valid entries are published to the registry as <code>human_seed</code> versions (operator <code>human_seed</code>, job id null, an auto-created seed hypothesis whose mechanism is the owner's notes) and added to the factor pool with status <code>seed</code>. Strategies in the file are published as strategy versions and added to the strategy pool as <code>seed</code>.</li>
  <li>The evaluator pulls and evaluates the seed versions like any others. Their W1 official records make them the correlation library and give the owner real numbers for their own factors.</li>
  <li>Import is repeatable: re-importing the same expression is idempotent on content hash; a changed expression becomes a new version of the same family when the name matches.</li>
</ul>

<h3 id="s-13-7"><span class="sn">13.7</span>Tool catalog</h3>
<p>Kinds: <span class="badge ro">read</span> changes nothing; <span class="badge rw">write</span> changes state and is audited; <span class="badge appr">approval</span> requires an approval record. Every tool returns structured JSON validated against a published schema, and every tool's description in the server is the single source of truth for its arguments.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Tool</th><th>Kind</th><th>Purpose and key arguments</th><th>Backend</th><th>Phase</th></tr></thead>
<tbody>
<tr><td><code>qfr.status</code></td><td><span class="badge ro">read</span></td><td>Health of every service, setup state, pool counts, active jobs, budgets used today, data freshness, burn meters, open alerts</td><td>All APIs' /healthz and summary routes</td><td>0, 7</td></tr>
<tr><td><code>qfr.config.get</code></td><td><span class="badge ro">read</span></td><td>Protocol card, policy card, charter defaults, providers and roles without secrets; with <code>owner_only=true</code>, window dates and private gates</td><td>feedback-api, eval-admin-api, research-api</td><td>0</td></tr>
<tr><td><code>qfr.logs.search</code></td><td><span class="badge ro">read</span></td><td>Filter by time range, service, level, event, any correlation id, free text; cursor and limit (default 200, max 2,000)</td><td>Logs volume</td><td>0</td></tr>
<tr><td><code>qfr.logs.tail</code></td><td><span class="badge ro">read</span></td><td>Last n lines of one service or all services</td><td>Logs volume</td><td>0</td></tr>
<tr><td><code>qfr.logs.correlate</code></td><td><span class="badge ro">read</span></td><td>All lines from every service carrying a given id (job, generation, task, run, candidate, version, record, request), ordered by time</td><td>Logs volume</td><td>0</td></tr>
<tr><td><code>qfr.logs.export</code></td><td><span class="badge rw">write</span></td><td>Write a filtered log slice as a compressed JSON-lines file to <code>exports/logs/</code>; same filters as search</td><td>Logs volume, exports mount</td><td>7</td></tr>
<tr><td><code>qfr.setup.status</code></td><td><span class="badge ro">read</span></td><td>Setup state, probe results per model, snapshot ids, pool counts, "no defaults" notice</td><td>control_db, research-api, eval-admin-api</td><td>2, 4</td></tr>
<tr><td><code>qfr.pool.import</code></td><td><span class="badge rw">write</span></td><td>Import a raw pool file from <code>imports/</code> or inline entries; returns per-entry outcome with reason codes</td><td>registry-api publish and pool routes</td><td>2</td></tr>
<tr><td><code>qfr.pool.list</code>, <code>qfr.pool.get</code></td><td><span class="badge ro">read</span></td><td>Pool entries with status, tier, tags, evidence tier and latest released state</td><td>registry-api, eval-admin-api</td><td>2</td></tr>
<tr><td><code>qfr.pool.add</code></td><td><span class="badge appr">approval</span></td><td>Add an approved version to a pool with the tier reached</td><td>registry-api pool routes</td><td>6</td></tr>
<tr><td><code>qfr.pool.set_status</code></td><td><span class="badge appr">approval</span></td><td>Retire or re-approve an entry; appends an event</td><td>registry-api pool routes</td><td>6</td></tr>
<tr><td><code>qfr.pool.annotate</code></td><td><span class="badge rw">write</span></td><td>Append tags and notes</td><td>registry-api pool routes</td><td>6</td></tr>
<tr><td><code>qfr.dsl.validate</code></td><td><span class="badge ro">read</span></td><td>Parse, type-check and constrain an expression; return the canonical form, complexity and a plain-language explanation</td><td>qfr_core in-process</td><td>2</td></tr>
<tr><td><code>qfr.artifact.get</code></td><td><span class="badge ro">read</span></td><td>Manifest and server fields of a version</td><td>registry-api</td><td>2</td></tr>
<tr><td><code>qfr.lineage.get</code></td><td><span class="badge ro">read</span></td><td>Parents and children to a depth, with AST diffs</td><td>registry-api, research-api</td><td>4</td></tr>
<tr><td><code>qfr.job.submit</code></td><td><span class="badge rw">write</span></td><td>Validate a brief, publish seeds, derive a charter, start the program; returns job id and timeline estimate</td><td>research-api</td><td>4</td></tr>
<tr><td><code>qfr.job.list</code>, <code>qfr.job.get</code>, <code>qfr.job.events</code></td><td><span class="badge ro">read</span></td><td>Jobs, their state, generations, publications, costs and events since a cursor</td><td>research-api</td><td>4</td></tr>
<tr><td><code>qfr.job.wait</code></td><td><span class="badge ro">read</span></td><td>Long-poll until the job changes state or the timeout (≤ 600 s) expires</td><td>research-api</td><td>4</td></tr>
<tr><td><code>qfr.job.steer</code></td><td><span class="badge rw">write</span></td><td>Append owner guidance to the charter for the next generation; scanned like a brief</td><td>research-api</td><td>4</td></tr>
<tr><td><code>qfr.job.pause</code>, <code>qfr.job.resume</code>, <code>qfr.job.cancel</code></td><td><span class="badge rw">write</span></td><td>Stop or restart spending on a job</td><td>research-api</td><td>4</td></tr>
<tr><td><code>qfr.job.close</code></td><td><span class="badge appr">approval</span></td><td>Close a delivered job as approved or rejected with the owner's words</td><td>research-api, control_db</td><td>6</td></tr>
<tr><td><code>qfr.deliverable.list</code>, <code>qfr.deliverable.get</code></td><td><span class="badge ro">read</span></td><td>Deliverables of a job, composed with owner-grade evidence</td><td>research-api, eval-admin-api</td><td>4</td></tr>
<tr><td><code>qfr.deliverable.export</code></td><td><span class="badge rw">write</span></td><td>Write a bundle to <code>exports/</code>; returns the path and hashes</td><td>research-api, eval-admin-api, exports mount</td><td>7</td></tr>
<tr><td><code>qfr.evidence.get</code></td><td><span class="badge ro">read</span></td><td>Owner-grade evidence for a version: official records, gate values, series refs, simulation state</td><td>eval-admin-api</td><td>4, 6</td></tr>
<tr><td><code>qfr.report.list</code></td><td><span class="badge ro">read</span></td><td>Released reports for a version, family or job, as research saw them</td><td>feedback-api</td><td>4</td></tr>
<tr><td><code>qfr.trace.get</code>, <code>qfr.trace.export</code></td><td><span class="badge ro">read</span></td><td>The development trace of a version or candidate; export writes <code>trace.json</code> and a Markdown rendering to <code>exports/</code></td><td>research-api</td><td>4, 7</td></tr>
<tr><td><code>qfr.approval.record</code></td><td><span class="badge rw">write</span></td><td>Create an approval record from the owner's verbatim confirmation; returns the approval id</td><td>control_db</td><td>6</td></tr>
<tr><td><code>qfr.acceptance.list_cases</code></td><td><span class="badge ro">read</span></td><td>Open and decided acceptance cases with gate values</td><td>eval-admin-api</td><td>6</td></tr>
<tr><td><code>qfr.acceptance.decide</code></td><td><span class="badge appr">approval</span></td><td>Accept or reject a case; cannot contradict a failed gate in v1</td><td>eval-admin-api</td><td>6</td></tr>
<tr><td><code>qfr.ops.alerts</code></td><td><span class="badge ro">read</span></td><td>Monitoring, staleness, burn and provider alerts, open or acknowledged</td><td>eval-admin-api, research-api</td><td>6, 7</td></tr>
<tr><td><code>qfr.ops.costs</code></td><td><span class="badge ro">read</span></td><td>Cost by job, generation, provider, model and role over a period</td><td>research-api</td><td>4</td></tr>
<tr><td><code>qfr.ops.pause_research</code>, <code>qfr.ops.resume_research</code></td><td><span class="badge rw">write</span></td><td>Pause or resume every program, for incidents</td><td>research-api</td><td>7</td></tr>
<tr><td><code>qfr.ops.activate_protocol</code>, <code>qfr.ops.activate_policy</code>, <code>qfr.ops.activate_quotas</code></td><td><span class="badge rw">write</span></td><td>Activate a new version of an evaluator configuration file placed under <code>imports/</code></td><td>eval-admin-api</td><td>3, 7</td></tr>
<tr><td><code>qfr.ops.rollover_epoch</code></td><td><span class="badge appr">approval</span></td><td>Phase 8 epoch rollover</td><td>eval-admin-api</td><td>8</td></tr>
</tbody>
</table>
</div>
<p>Test MCP-02 snapshots this catalog: no tool may publish artifacts, call research tools, write official records, alter runs or queues, or read research-zone data files.</p>

<h3 id="s-13-8"><span class="sn">13.8</span>Resources and prompts</h3>
<div class="grid-2">
<div class="card"><h4>Resources (read-only, cacheable by the client)</h4>
<ul style="margin:6px 0 0;padding-left:18px;font-size:14px">
<li><code>qfr://cards/protocol</code> and <code>qfr://cards/policy</code></li>
<li><code>qfr://pools/factors</code> and <code>qfr://pools/strategies</code></li>
<li><code>qfr://jobs/{job_id}</code> and <code>qfr://deliverables/{deliverable_id}</code></li>
<li><code>qfr://trace/{version_id}</code></li>
<li><code>qfr://docs/host-agent-guide</code> (the full text of <code>docs/HOST_AGENT_GUIDE.md</code>)</li>
<li><code>qfr://schemas/{name}</code> for brief/1, deliverable/1, approval/1, trace/1, iteration_history/1, pool_import/1</li>
</ul></div>
<div class="card"><h4>Prompts (how the host agent should work)</h4>
<ul style="margin:6px 0 0;padding-left:18px;font-size:14px">
<li><code>qfr.brief</code>: turn the owner's intent into a brief; which mode fits which request; how to extract expressions from documents; what never to put in a brief.</li>
<li><code>qfr.report_deliverable</code>: how to present a deliverable: tier first, then evidence, then caveats, then the short codes for approval.</li>
<li><code>qfr.approval</code>: how to ask for and record an approval verbatim.</li>
<li><code>qfr.investigate</code>: how to use traces and logs to answer "how did this factor come about" and "what happened to job X".</li>
</ul></div>
</div>

<h3 id="s-13-9"><span class="sn">13.9</span>Host-agent operating rules</h3>
<p>These are the rules the host agent follows; the full guide is <code>docs/HOST_AGENT_GUIDE.md</code>, summarized in <a href="#s-21-3">Section 21.3</a>.</p>
<ol>
  <li>Read the cards and the pools before writing a brief. Validate every expression with <code>qfr.dsl.validate</code>.</li>
  <li>Never paste owner-only numbers into a brief or steering note. Reference ids instead.</li>
  <li>Always report the evidence tier reached, the number of trials counted, and the caveats, in the deliverable's own words.</li>
  <li>Never record an approval the owner did not state. Quote the owner; include the short codes.</li>
  <li>Prefer <code>qfr.job.wait</code> over polling loops. Respect pauses and budgets the owner sets.</li>
  <li>When something looks wrong, use <code>qfr.logs.correlate</code> and <code>qfr.trace.get</code> before guessing.</li>
</ol>
</section>
<!-- ===================================================== CHAPTER 14 -->
<section class="chapter" id="ch-14">
<div class="chapter-kicker"><span class="n">14</span>Chapter 14</div>
<h2>Development trace: making factor evolution traceable<a class="anchor" href="#ch-14">#</a></h2>
<p class="lead">If factor evolution is left to LLMs alone, the result is a black box: a factor appears, and nobody can say which idea it came from, which prompt produced it, what was tried and discarded on the way, or why one version replaced another. QFR records every step of a factor's development so that the path from the original brief to the delivered version can be inspected, exported and audited without trusting any LLM's account of it.</p>

<h3 id="s-14-1"><span class="sn">14.1</span>Why a trace, and what it is not</h3>
<ul>
  <li>The trace is <strong>deterministic code's record of what happened</strong>, written by the tool layer, the workflow, the packager, the evaluator and the front door. Agents never write trace steps directly, and no step is generated by an LLM.</li>
  <li>The trace is <strong>complete by construction</strong>: a version cannot be published unless its required steps exist (INV-13).</li>
  <li>The trace is <strong>append-only</strong> and lives in insert-only tables protected by triggers, like official records.</li>
  <li>The trace is <strong>not a reproduction guarantee for LLM output</strong>. Providers are nondeterministic. The trace stores the exact request and the exact response so each LLM step is inspectable and replayable as recorded, and every deterministic step (validation, workbench numbers, selection, evaluation) is reproducible from its pinned inputs.</li>
</ul>

<h3 id="s-14-2"><span class="sn">14.2</span>What is recorded along the path</h3>
<figure id="fig-4">
<div class="trace-pipe">
  <div class="tp"><span class="num">1</span><b>Brief received</b><span class="who own">owner · host agent</span><ul><li>brief/1 as submitted</li><li>derived charter version</li><li>seed version ids</li><li>scan result</li></ul></div>
  <div class="tp"><span class="num">2</span><b>Generation planned</b><span class="who llm">supervisor</span><ul><li>proposal (bandit state, parents)</li><li>plan + validator verdict</li><li>full prompt and response</li><li>provider, model, cost</li></ul></div>
  <div class="tp"><span class="num">3</span><b>Hypothesis proposed</b><span class="who llm">hypothesis researcher</span><ul><li>task brief and context ids</li><li>full prompt and response</li><li>Hypothesis object</li><li>similar hypotheses shown</li></ul></div>
  <div class="tp"><span class="num">4</span><b>Parent selected</b><span class="who det">evolution engine</span><ul><li>operator, selection rule, random seed</li><li>parent version ids and fitness</li><li>targeted flags</li></ul></div>
  <div class="tp"><span class="num">5</span><b>Draft produced</b><span class="who llm">factor engineer</span><ul><li>DSL card version</li><li>full prompt and response</li><li>CandidateDraft or StrategyDraft</li><li>tool calls made</li></ul></div>
  <div class="tp"><span class="num">6</span><b>Validated</b><span class="who det">dsl.validate</span><ul><li>parse and constraint results</li><li>canonical form and hash</li><li>complexity, lookback</li><li>AST diff to parent</li></ul></div>
  <div class="tp"><span class="num">7</span><b>Workbench measured</b><span class="who det">workbench</span><ul><li>W0 metrics, labelled in-sample</li><li>research snapshot id</li><li>similarity to pools and population</li></ul></div>
  <div class="tp"><span class="num">8</span><b>Reviewed</b><span class="who llm">critic (other provider)</span><ul><li>full prompt and response</li><li>ReviewVerdict and scores</li><li>revision rounds, each recorded</li></ul></div>
  <div class="tp"><span class="num">9</span><b>Pre-screened and selected</b><span class="who det">evolution engine</span><ul><li>pre-screen checks and values</li><li>provisional fitness and rank</li><li>selected or not, and why</li></ul></div>
  <div class="tp"><span class="num">10</span><b>Published</b><span class="who det">packager</span><ul><li>completeness check result</li><li>manifest and content hash</li><li>version id, family, version_no</li><li>lineage edges</li></ul></div>
  <div class="tp"><span class="num">11</span><b>Evaluated</b><span class="who eval">evaluator</span><ul><li>intake decision, reason codes</li><li>official records (owner-grade)</li><li>released reports (research-grade)</li><li>trial ledger rows</li></ul></div>
  <div class="tp"><span class="num">12</span><b>Interpreted</b><span class="who llm">analyst · reviewer</span><ul><li>full prompts and responses</li><li>interpretation and challenge</li><li>knowledge items created</li></ul></div>
  <div class="tp"><span class="num">13</span><b>Delivered</b><span class="who det">job monitor</span><ul><li>criteria evaluated</li><li>deliverable id and tier</li><li>iteration history hash</li><li>fetch time by host agent</li></ul></div>
  <div class="tp"><span class="num">14</span><b>Approved and pooled</b><span class="who own">owner via MCP</span><ul><li>approval record id</li><li>owner's words verbatim</li><li>pool entry and events</li><li>later tier changes and alerts</li></ul></div>
</div>
<figcaption><b>Figure 4. What the trace records.</b> Blue steps are LLM actions and store the full request and response. Purple steps are deterministic research code. Green steps belong to the evaluator and are joined by version id. Pink steps are the owner's. A factor that went through five mutations has this sequence five times, linked by lineage edges.</figcaption>
</figure>

<h3 id="s-14-3"><span class="sn">14.3</span>Trace model</h3>
<p>The trace is one table of steps in research_db plus the full agent runs, joined at read time with registry lineage, evaluation records and approvals.</p>
<pre><code>trace_steps (research_db, insert-only)
  step_id        UUIDv7
  at             timestamptz
  job_id, program_id, generation_id, task_id        nullable where not applicable
  candidate_id   nullable until a draft exists
  version_id     nullable until published; back-filled by a PUBLISHED step, never by update
  step_type      enum, see below
  actor_kind     owner | host_agent | llm | deterministic | evaluator
  actor          role name, or service name
  provider, model_id, prompt_template_id, prompt_sha256, run_id     for llm steps
  inputs         JSONB of ids and hashes the step consumed (parents, reports, knowledge items, DSL card version)
  payload        JSONB: the structured output or decision of the step (validated by the step type's schema)
  outcome        ok | failed | retried | fallback
  request_id     the correlating request id, also present in the logs

agent_runs (research_db, insert-only)
  run_id, step_id, role, provider, model_id, prompt_template_id, prompt_sha256
  request_messages   JSONB, the full rendered messages sent
  response_text      the full raw response, including reasoning content when returned separately
  response_json      the parsed structured output, if any
  usage              tokens in, out, cached; cost; latency; finish reason; provider request id
  settings           temperature, output mode, usage limits</code></pre>
<p>Step types: BRIEF_RECEIVED, SEEDS_PUBLISHED, CHARTER_DERIVED, GENERATION_STARTED, PROPOSAL_EMITTED, PLAN_WRITTEN, PLAN_VALIDATED, HYPOTHESIS_PROPOSED, PARENT_SELECTED, PROMPT_SENT, MODEL_RESPONDED, PROVIDER_FALLBACK, DRAFT_CREATED, DSL_VALIDATED, WORKBENCH_EVALUATED, SIMILARITY_CHECKED, CRITIC_REVIEWED, REVISION_REQUESTED, REVISED, PRESCREEN_EVALUATED, SELECTED, NOT_SELECTED, TRACE_CHECKED, PUBLISHED, REPORT_RECEIVED, INTERPRETED, INTERPRETATION_CHALLENGED, KNOWLEDGE_ADDED, MUTATION_APPLIED, CROSSOVER_APPLIED, SYNTACTIC_MUTATION_APPLIED, REPAIR_APPLIED, STRATEGY_COMPOSED, DELIVERABLE_CRITERIA_EVALUATED, DELIVERABLE_ASSEMBLED, DELIVERED, STEERING_ADDED, JOB_STATE_CHANGED. Owner-side steps (APPROVAL_RECORDED, POOL_EVENT) live in control_db and registry_db and are joined by ids.</p>
<ul>
  <li>Every LLM call produces at least PROMPT_SENT and MODEL_RESPONDED (or a failure outcome) and exactly one <code>agent_runs</code> row. The tool layer records the tool calls inside the run as part of <code>request_messages</code> and <code>response_text</code>.</li>
  <li>Every deterministic decision that changes what happens next (selection, validation, pre-screen, completeness) is a step with the values it used, not just the verdict.</li>
  <li>Evaluator records are not copied into research_db. The trace export joins them by version id through the eval admin API, and the join is labelled owner-only.</li>
</ul>

<h3 id="s-14-4"><span class="sn">14.4</span>Iteration history</h3>
<p>The iteration history is the owner-facing rendering of the trace for one delivered version: how it developed from the original seed or hypothesis to the deliverable. It is generated by a deterministic template from trace steps and lineage edges, and it is attached to every deliverable.</p>
<pre><code>IterationHistory (schema iteration_history/1)
  version_id, job_id, generated_at, trace_hash
  roots[]           human_seed versions or explore hypotheses the lineage starts from
  hops[]            ordered from root to the delivered version; a crossover hop has two from_version_ids
    from_version_ids[], to_version_id or candidate_id
    generation_seq, operator, targeted_flags[]
    hypothesis_title, change_summary                      (as written by the engineer, labelled as such)
    expression_before, expression_after, ast_diff         (canonical forms, deterministic diff)
    engineer   {provider, model_id, prompt_template_id, run_id}
    critic     {provider, model_id, verdict, scores, rounds}
    workbench  {W0 RankIC, IR, coverage, similarity}      labelled in-sample
    evaluation {released W1/W2 fields as research saw them; owner_grade: official numbers per window}
    outcome    published | not_selected | screen_failed | gate_failed | advanced | ...
  discarded[]       sibling candidates from the same tasks that were not selected, with the reason
  totals            hops, LLM calls, tokens, cost, trials counted in this family</code></pre>
<p>The Markdown rendering shows one section per hop with the expression diff, the reason for the change, who made it (role, provider, model) and what the evidence said before and after. The host agent presents it to the owner; it may summarize but <span class="kw">MUST</span> keep the hop order, the operators and the evidence tiers.</p>

<h3 id="s-14-5"><span class="sn">14.5</span>Completeness rule and exports</h3>
<p>Before publishing, the packager runs TRACE_CHECKED and refuses to publish a candidate whose trace lacks any required step for its operator:</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Operator</th><th>Required steps before PUBLISHED</th></tr></thead>
<tbody>
<tr><td>explore</td><td>BRIEF_RECEIVED (job), PLAN_WRITTEN, HYPOTHESIS_PROPOSED, PROMPT_SENT and MODEL_RESPONDED for the engineer, DRAFT_CREATED, DSL_VALIDATED, WORKBENCH_EVALUATED, SIMILARITY_CHECKED, CRITIC_REVIEWED, PRESCREEN_EVALUATED, SELECTED</td></tr>
<tr><td>llm_mutation, crossover, repair</td><td>As explore, with PARENT_SELECTED and the operator's APPLIED step instead of HYPOTHESIS_PROPOSED, and parents present in lineage</td></tr>
<tr><td>syntactic_mutation</td><td>PARENT_SELECTED, SYNTACTIC_MUTATION_APPLIED with the rule and seed, DSL_VALIDATED, WORKBENCH_EVALUATED, SIMILARITY_CHECKED, PRESCREEN_EVALUATED, SELECTED (no LLM steps)</td></tr>
<tr><td>compose_strategy</td><td>STRATEGY_COMPOSED with the candidate set, the engineer's PROMPT_SENT and MODEL_RESPONDED, DRAFT_CREATED, DSL_VALIDATED for every component, WORKBENCH_EVALUATED (composite), CRITIC_REVIEWED, PRESCREEN_EVALUATED, SELECTED</td></tr>
<tr><td>human_seed</td><td>SEEDS_PUBLISHED with the import or brief reference and DSL_VALIDATED</td></tr>
</tbody>
</table>
</div>
<ul>
  <li>A refusal is itself a step (TRACE_CHECKED with outcome failed) and a WARNING log line; the candidate stays <code>approved</code> but <code>not_selected</code> with reason TRACE_INCOMPLETE, and the generation continues.</li>
  <li><strong>Trace export</strong> (<code>trace/1</code>): all steps for a version and its ancestors, ordered by (at, step_id), with agent runs inlined, lineage edges, released reports, and, in the owner export only, official records. The export is canonical JSON and its SHA-256 is the <code>trace_hash</code> stored on the deliverable. <code>qfr.trace.export</code> and <code>qfr trace export</code> write it to <code>exports/</code> with a Markdown rendering.</li>
  <li><strong>Tests:</strong> TRC-01 (publication refused when a required step is missing), TRC-02 (every LLM step has full request and response and a matching log line), TRC-03 (every operator application has an AST diff and parents, and the iteration history reconstructs every hop of a five-generation synthetic lineage).</li>
</ul>

<h3 id="s-14-6"><span class="sn">14.6</span>Limits and sizing</h3>
<ul>
  <li>Storage: a prompt is at most 12,000 tokens; a generation makes roughly 40 to 80 LLM calls; at 4 generations a day the trace grows by about 15 to 25 MB per day of text, under 10 GB per year. Everything is retained for v1; no pruning.</li>
  <li>Secrets never enter the trace: keys are not in prompts, and the redaction processor runs on agent runs before insert.</li>
  <li>Owner-only evidence never enters research_db; the owner export joins it at read time.</li>
  <li>The trace tells the owner <em>how</em> a factor was developed; it does not claim the development was correct. That is what the evaluator and the gates are for.</li>
</ul>
</section>

<!-- ===================================================== CHAPTER 15 -->
<section class="chapter" id="ch-15">
<div class="chapter-kicker"><span class="n">15</span>Chapter 15</div>
<h2>Logging: record everything, readable through MCP<a class="anchor" href="#ch-15">#</a></h2>
<p class="lead">Every action inside QFR is logged as a structured JSON line with correlation ids. Logs from every service land on one volume. The host agent can search, tail and correlate them through MCP, and the owner can open the files on the Mac. There is no log stack to operate.</p>

<h3 id="s-15-1"><span class="sn">15.1</span>Principles</h3>
<ul>
  <li><strong>Log everything, once, in one shape.</strong> One logger (structlog), one JSON schema for a line, one sink layout. Every service, including qfr-mcp and one-shot jobs, logs the same way.</li>
  <li><strong>Correlation over verbosity.</strong> A line is useful because it carries the ids that tie it to a job, a version, a run or a request. Lines without ids are a bug.</li>
  <li><strong>Logs are internal, releases are external.</strong> Logs may contain anything the owner may see, including stack traces and full-precision numbers. They are never a feedback channel to research: research containers cannot read any log directory but their own.</li>
  <li><strong>No secrets, ever.</strong> A redaction processor runs on every line before any sink.</li>
  <li><strong>Simple storage.</strong> JSON-lines files per service per day on a named volume, plus stdout for <code>docker compose logs</code>. No database table for logs; audit events in the databases are separate and smaller.</li>
</ul>

<h3 id="s-15-2"><span class="sn">15.2</span>Mandatory fields and correlation ids</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Field</th><th>Always</th><th>Meaning</th></tr></thead>
<tbody>
<tr><td>ts</td><td>yes</td><td>UTC timestamp with microseconds</td></tr>
<tr><td>level</td><td>yes</td><td>DEBUG, INFO, WARNING, ERROR, CRITICAL</td></tr>
<tr><td>service</td><td>yes</td><td>qfr-mcp, research-api, research-worker, registry-api, eval-scheduler, eval-worker, release-worker, sim-engine, feedback-api, eval-admin-api, data-ingest, migrate, cli</td></tr>
<tr><td>zone</td><td>yes</td><td>control, research, registry, eval</td></tr>
<tr><td>event</td><td>yes</td><td>A stable snake_case event name, for example <code>llm_call_completed</code>, <code>intake_decision</code>, <code>mcp_tool_called</code></td></tr>
<tr><td>request_id</td><td>yes</td><td>Generated at the edge (MCP call, API request, scheduler tick) and propagated through HTTP headers and the job payload</td></tr>
<tr><td>principal</td><td>when known</td><td>Token id or role that caused the action</td></tr>
<tr><td>job_id, program_id, generation_id, task_id, run_id, candidate_id, version_id, family_id, record_id, report_id, case_id, sim_id, step_id</td><td>when applicable</td><td>Correlation ids. Any line that concerns an entity carries that entity's id</td></tr>
<tr><td>duration_ms</td><td>for completed operations</td><td>Wall time</td></tr>
<tr><td>outcome</td><td>for completed operations</td><td>ok, failed, retried, skipped, deferred, fallback</td></tr>
<tr><td>error_code, error_type, stack</td><td>on errors</td><td>Error code from the fixed vocabulary, exception type, stack trace</td></tr>
<tr><td>payload</td><td>optional</td><td>Event-specific fields; large values are digests with sizes</td></tr>
</tbody>
</table>
</div>
<p>Propagation: contextvars bind the ids inside a process; HTTP clients send <code>X-Request-Id</code> and <code>X-QFR-Job-Id</code> and servers bind them; queue payloads carry the ids; the MCP server generates a request id per call and returns it in the tool result so the host agent can quote it.</p>

<h3 id="s-15-3"><span class="sn">15.3</span>What is logged</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Where</th><th>Events</th><th>Level</th></tr></thead>
<tbody>
<tr><td>Every service</td><td>Startup with configuration digest (no secrets), config version ids, snapshot ids; shutdown; health checks failing</td><td>INFO</td></tr>
<tr><td>Every API</td><td>Every request: method, path, principal, status, duration, request id; every validation failure with field paths</td><td>INFO, WARNING on 4xx</td></tr>
<tr><td>Repository layer</td><td>Every write: table, entity id, action, principal; mirrored to the database's audit events table</td><td>INFO</td></tr>
<tr><td>Queues</td><td>Job claimed, started, finished, failed, retried, with attempt and backoff</td><td>INFO</td></tr>
<tr><td>Research workflow</td><td>Every job and generation state transition; plan, validator verdict and fallback; task start and end; budget checks and refusals</td><td>INFO</td></tr>
<tr><td>Provider layer</td><td>Every LLM call: role, provider, model, template id, prompt sha, tokens in/out/cached, cost, latency, finish reason, output mode, retries, fallback switches, provider request id (full text is in agent_runs, not logs)</td><td>INFO, WARNING on retry or fallback</td></tr>
<tr><td>Tool layer</td><td>Every agent tool call: role, tool, argument digest, result digest, latency, permission denials</td><td>INFO, WARNING on denial</td></tr>
<tr><td>Evolution engine</td><td>Fitness updates, archive changes, bandit draws and allocations, selection choices with seeds, pre-screen results, diversity guardrail triggers, migrations, stagnation decisions</td><td>INFO</td></tr>
<tr><td>Packager</td><td>Trace check result, manifest hash, publication response, idempotent hits</td><td>INFO, WARNING on refusal</td></tr>
<tr><td>Registry</td><td>Publish decisions, dedup hits, pool entries and events with approval ids</td><td>INFO</td></tr>
<tr><td>Intake and scheduler</td><td>Cursor positions, each intake decision with reason code, dedup matches, quota deferrals and expiries, library sync changes, queue depth</td><td>INFO</td></tr>
<tr><td>Evaluation workers</td><td>Run start and end with pinned inputs, screening results and values, each gate evaluated with values, record and ledger ids, results hash, runtime and memory</td><td>INFO</td></tr>
<tr><td>Release engine</td><td>Each report queued and released with both times, released fields, withheld fields and the rule that withheld them, Ladder decisions, burn meter updates</td><td>INFO</td></tr>
<tr><td>Simulation</td><td>Per day: orders, fills, blocked trades, NAV, checkpoints, staleness, data revisions</td><td>INFO</td></tr>
<tr><td>Acceptance and monitoring</td><td>Case opened with gate values, decisions with approval ids, alerts raised and acknowledged</td><td>INFO, WARNING for alerts</td></tr>
<tr><td>Data ingest</td><td>Download, checksum verification, sanity checks with counts, snapshot ids built, zone truncation cutoff</td><td>INFO, ERROR on failed checks</td></tr>
<tr><td>MCP front door</td><td>Every tool call: tool, principal, argument digest, result size, duration, outcome, downstream request ids; approvals recorded with scope; scan rejections; token failures</td><td>INFO, WARNING on rejection</td></tr>
<tr><td>Anywhere</td><td>Exceptions with stack traces; boundary test failures in deployed environments at CRITICAL</td><td>ERROR, CRITICAL</td></tr>
</tbody>
</table>
</div>
<p>DEBUG adds per-row detail (for example per-date metric values) and is off by default; it can be enabled per service with <code>QFR_LOG_LEVEL</code> without a rebuild.</p>

<h3 id="s-15-4"><span class="sn">15.4</span>Storage and retention</h3>
<ul>
  <li>Sinks: stdout (for <code>docker compose logs</code>) and a file per service per day at <code>/var/log/qfr/&lt;service&gt;/&lt;YYYY-MM-DD&gt;.jsonl</code> on the named volume <code>qfr_logs</code>. Writes are line-buffered and append-only.</li>
  <li>Rotation: daily by date; a file that exceeds 512 MB rolls to <code>.partN.jsonl</code>. Files older than 7 days are gzip-compressed by the nightly job; files older than 180 days are deleted. Both thresholds are configuration.</li>
  <li>Mounts: each service mounts only its own directory read-write. <code>qfr-mcp</code> mounts the whole volume read-only. Research containers have no mount of any evaluation or control directory (test BND-08).</li>
  <li>Disk guard: the nightly job logs a WARNING and raises an alert when the volume exceeds 20 GB.</li>
  <li>Expected volume: tens of thousands of lines per day in normal operation, well under 1 GB per day uncompressed even with four generations and 200 W1 runs.</li>
</ul>

<h3 id="s-15-5"><span class="sn">15.5</span>Reading logs through MCP and the CLI</h3>
<p>The MCP tools read the files directly and need no index. A search is a filtered scan of the day files in range; with the default limits it returns in well under a second for a week of logs.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Tool</th><th>Arguments</th><th>Returns</th></tr></thead>
<tbody>
<tr><td><code>qfr.logs.search</code></td><td>from, to (default last 24 hours; ranges over 7 days require explicit dates), services[], levels[], events[], any correlation id field, text (substring on the raw line), cursor, limit (default 200, max 2,000)</td><td>Lines as JSON objects, newest last, with a cursor for the next page and the count scanned</td></tr>
<tr><td><code>qfr.logs.tail</code></td><td>service or all, n (default 100, max 2,000)</td><td>The last n lines</td></tr>
<tr><td><code>qfr.logs.correlate</code></td><td>id, id_kind (job, generation, task, run, candidate, version, record, request, case, sim), from, to</td><td>Every line from every service carrying the id, ordered by time, grouped by service; plus a one-line timeline summary of state transitions</td></tr>
<tr><td><code>qfr.logs.export</code></td><td>the same filters as search</td><td>Writes a <code>.jsonl.gz</code> slice to <code>exports/logs/</code> and returns its path (Phase 7)</td></tr>
</tbody>
</table>
</div>
<p>The CLI <code>qfr logs search|tail|correlate|export</code> exposes the same operations on the Mac, and <code>docker compose logs -f &lt;service&gt;</code> works for live watching. Typical host-agent uses: "why did version X fail screening" (correlate version id, read the eval-worker lines with reason codes and values), "what did job Y cost so far" (search event <code>llm_call_completed</code> with job id and sum the cost field, or call <code>qfr.ops.costs</code>), "did anything error overnight" (search level ERROR in the last 24 hours).</p>

<h3 id="s-15-6"><span class="sn">15.6</span>Redaction and what logs never contain</h3>
<ul>
  <li>The redaction processor replaces the value of any field whose name matches <code>(api_key|token|authorization|password|secret|cookie)</code>, case-insensitive, and any string matching known key shapes (for example <code>sk-</code> followed by 20 or more alphanumerics) anywhere in a line, with <code>[REDACTED]</code>. Test LOG-02 injects a fake key through every service and asserts it never appears in any sink.</li>
  <li>Full prompt and response texts are not logged; they live in <code>agent_runs</code> and are referenced by run id.</li>
  <li>Raw market data rows are not logged; snapshot ids and counts are.</li>
  <li>Logs are not released to research in any form, and the Feedback API has no route to them.</li>
</ul>
</section>
<!-- ===================================================== CHAPTER 16 -->
<section class="chapter" id="ch-16">
<div class="chapter-kicker"><span class="n">16</span>Chapter 16</div>
<h2>Data model and APIs<a class="anchor" href="#ch-16">#</a></h2>
<p>Conventions for all databases: primary keys are UUIDv7 (time-ordered); all timestamps are timestamptz in UTC; JSONB columns hold flexible payloads validated by Pydantic models before insert; every row records the principal that created it; insert-only tables are protected by triggers that raise on UPDATE and DELETE; migrations use Alembic, with one environment per database.</p>

<h3 id="s-16-1"><span class="sn">16.1</span>registry_db</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Table</th><th>Key columns</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>artifact_families</td><td>family_id, kind, program_id, job_id, name, created_at, created_by</td><td>One row per lineage family</td></tr>
<tr><td>artifact_versions</td><td>version_id, family_id, version_no, kind, manifest (JSONB), payload_text, content_hash (unique), canonical_hash, published_seq (bigserial, unique), published_at, publisher</td><td>Insert-only. Unique on (family_id, version_no)</td></tr>
<tr><td>artifact_parents</td><td>version_id, parent_version_id, relation, ast_diff (JSONB)</td><td>Insert-only. Primary key on the pair</td></tr>
<tr><td>pool_entries</td><td>entry_id, pool (factor or strategy), version_id, title, created_at, created_by, approval_id</td><td>Insert-only. Unique on (pool, version_id)</td></tr>
<tr><td>pool_events</td><td>event_id, event_seq (bigserial, unique), entry_id, at, principal, action (ADDED, STATUS_CHANGED, ANNOTATED), from_status, to_status, approved_tier, approval_id, tags, note, request_id</td><td>Insert-only. The evaluator pulls by event_seq</td></tr>
<tr><td>pool_current_v (view)</td><td>entry_id, pool, version_id, status, approved_tier, tags, title, last_event_at</td><td>Latest event per entry</td></tr>
<tr><td>registry_events</td><td>event_id, at, principal, action, version_id, entry_id, request_id, payload</td><td>Insert-only audit</td></tr>
</tbody>
</table>
</div>

<h3 id="s-16-2"><span class="sn">16.2</span>research_db (blackboard, jobs and trace)</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Table</th><th>Key columns</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>research_jobs</td><td>job_id, short_code, brief (JSONB), state, program_id, parent_job_id, deliverable_criteria, budget, cost_cny, submitted_at, closed_at, close_decision, approval_id</td><td>The owner's jobs</td></tr>
<tr><td>job_events</td><td>event_id, job_id, seq, at, kind, payload</td><td>Insert-only; served by qfr.job.events</td></tr>
<tr><td>deliverables</td><td>deliverable_id, job_id, status (complete or best_effort), summary, costs, created_at, fetched_at</td><td></td></tr>
<tr><td>deliverable_items</td><td>item_id, deliverable_id, version_id, kind, tier_reached, iteration_history (JSONB), trace_hash, short_code</td><td>Owner-grade evidence is joined at read time by qfr-mcp, never stored here</td></tr>
<tr><td>programs</td><td>program_id, job_id, name, status (active or paused), charter, charter_version, created_by</td><td>One per job</td></tr>
<tr><td>islands</td><td>island_id, program_id, key, theme, status</td><td></td></tr>
<tr><td>generations</td><td>generation_id, program_id, seq, state, proposal, plan, started_at, ended_at, cost_cny, summary</td><td>State machine row</td></tr>
<tr><td>tasks</td><td>task_id, generation_id, type, island_id, brief, parent_version_ids, hypothesis_id, state, attempts, error_code</td><td></td></tr>
<tr><td>hypotheses</td><td>hypothesis_id, program_id, island_id, payload, status (open, supported, weakened or retired), parent_hypothesis_id, source (agent or seed)</td><td></td></tr>
<tr><td>candidates</td><td>candidate_id, task_id, hypothesis_id, island_id, kind (factor or strategy), expression or components, canonical_hash, payload, workbench, state, provisional_fitness, version_id</td><td>version_id is set by the PUBLISHED step through an insert-only link table, candidate_versions</td></tr>
<tr><td>reviews</td><td>review_id, candidate_id, round, verdict, payload, run_id</td><td></td></tr>
<tr><td>population_members</td><td>member_id, program_id, island_id, version_id, status (official, provisional or archived), fitness, descriptors, updated_at</td><td></td></tr>
<tr><td>archive_cells</td><td>program_id, cell_key, elite_version_id, fitness, updated_at</td><td></td></tr>
<tr><td>lineage_edges</td><td>child_version_id, parent_version_id, relation, operator, ast_diff</td><td>Mirror of the registry lineage plus research details</td></tr>
<tr><td>report_cache</td><td>report_id, version_id, report_type, released_at, content, content_hash, fetched_at</td><td>Read-only copy of released reports. Never edited</td></tr>
<tr><td>report_links</td><td>link_id, report_id, entity_type, entity_id</td><td>Links reports to hypotheses, candidates and members</td></tr>
<tr><td>feedback_cursor</td><td>program_id, last_released_at, last_report_id</td><td></td></tr>
<tr><td>interpretations, interpretation_challenges</td><td>interpretation_id, report_ids, version_id, payload, status; challenge_id, interpretation_id, payload, verdict</td><td></td></tr>
<tr><td>knowledge_items</td><td>item_id, program_id, kind, statement, tags, evidence_report_ids</td><td></td></tr>
<tr><td>bandit_state</td><td>program_id, island_id, alpha, beta, updated_generation</td><td></td></tr>
<tr><td>budget_ledger</td><td>entry_id, job_id, program_id, generation_id, task_id, role, provider, model, tokens_in, tokens_out, tokens_cached, cost_cny, at</td><td>Insert-only</td></tr>
<tr><td>agent_runs</td><td>run_id, step_id, role, provider, model_id, prompt_template_id, prompt_sha256, request_messages, response_text, response_json, usage, settings, status, latency_ms</td><td>Insert-only. Full request and response text (<a href="#s-14-3">Section 14.3</a>)</td></tr>
<tr><td>trace_steps</td><td>step_id, at, job_id, program_id, generation_id, task_id, candidate_id, version_id, step_type, actor_kind, actor, provider, model_id, prompt_template_id, prompt_sha256, run_id, inputs, payload, outcome, request_id</td><td>Insert-only. Indexed on candidate_id, version_id, job_id</td></tr>
<tr><td>queue_jobs</td><td>queue_job_id, queue, payload, state, run_after, attempts, locked_by, locked_at</td><td>Postgres queue using SKIP LOCKED</td></tr>
<tr><td>events</td><td>event_id, at, principal, action, entity_type, entity_id, request_id, payload</td><td>Insert-only audit</td></tr>
</tbody>
</table>
</div>

<h3 id="s-16-3"><span class="sn">16.3</span>eval_db</h3>
<p>This database has two schemas. The <code>eval</code> schema is private to the evaluator and the owner. The <code>feedback</code> schema holds only the views granted to feedback_ro.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Table</th><th>Key columns</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>protocols, release_policies, quotas</td><td>id, version, yaml, sha256, status (draft, active or retired), activated_by, approval_id</td><td>Unique on (id, version). Immutable once active</td></tr>
<tr><td>epochs</td><td>epoch_id, config, status, started_at</td><td>Window dates live here</td></tr>
<tr><td>data_snapshots</td><td>snapshot_id, zone, manifest, created_at</td><td></td></tr>
<tr><td>intake, intake_cursor</td><td>version_id, content_hash, family_id, program_id, job_id, discovered_at, state, reason_code, duplicate_of; last_published_seq</td><td></td></tr>
<tr><td>pool_sync_cursor, library</td><td>last_event_seq; version_id, pool, status (seed, active, retired), approved_tier, effective_from (W1 record time), updated_at</td><td>The evaluator's view of the pools</td></tr>
<tr><td>queue_jobs</td><td>queue_job_id, queue, payload, state, run_after, attempts, locked_by, locked_at</td><td>Evaluation queue</td></tr>
<tr><td>runs</td><td>run_id, version_id, stage, window, protocol_ref, epoch_id, snapshot_id, code_version, image_digest, seed, status, started_at, finished_at, error_code</td><td></td></tr>
<tr><td>metrics</td><td>run_id, name, horizon, value</td><td>Full precision</td></tr>
<tr><td>series_files</td><td>run_id, kind, uri, sha256</td><td>Parquet files in the evaluation artifact store</td></tr>
<tr><td>official_records</td><td>record_id, version_id, content_hash, stage, window, run_ids, summary, results_hash, created_at</td><td>Insert-only</td></tr>
<tr><td>trial_ledger</td><td>window, epoch_id, version_id, family_id, program_id, job_id, sharpe_daily, n_obs, skew, kurt_raw, fingerprint_ref, counted_at</td><td>Insert-only</td></tr>
<tr><td>fingerprints, trial_clusters</td><td>version_id, epoch_id, uri; epoch_id, window, version_id, cluster_id, computed_at</td><td>Nightly N_eff job</td></tr>
<tr><td>quota_usage, burn_meters</td><td>scope, key, period_start, count; epoch_id, window, trials, released_values, queries_used, budget, status</td><td></td></tr>
<tr><td>release_queue, released_reports, ladder_state</td><td>record_id, report_type, due_at (the decision time), state; report_id, version_id, content_hash, family_id, program_id, report_type, policy_ref, protocol_card_ref, content, released_at; family_id, best_value, updated_at</td><td>released_reports is insert-only</td></tr>
<tr><td>sim_accounts, sim_orders, sim_fills, sim_positions, sim_nav</td><td>sim_id, version_id, mode (forward or replay), start_date, status, capital; per-table fields (instrument, shares, price, cost, NAV, cash, turnover)</td><td></td></tr>
<tr><td>acceptance_cases</td><td>case_id, version_id, gate_results, recommendation, state, decision, decided_at, rationale, approval_id</td><td>Decisions require an approval id</td></tr>
<tr><td>alerts</td><td>alert_id, kind (decay, staleness, burn, ops), version_id, at, details, state (open or acknowledged), acknowledged_by</td><td></td></tr>
<tr><td>events</td><td>event_id, at, principal, action, entity_type, entity_id, request_id, payload</td><td>Insert-only audit</td></tr>
</tbody>
</table>
</div>
<p>Views in the feedback schema: released_reports_v (filtered by the token's program ids), artifact_status_v (latest released status per version), library_v, policy_card_v, protocol_card_v.</p>

<h3 id="s-16-4"><span class="sn">16.4</span>control_db</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Table</th><th>Key columns</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>approvals</td><td>approval_id, created_at, decision, scope (JSONB), owner_confirmation, rationale, short_codes_matched, principal, request_id</td><td>Insert-only. Referenced by pool_events, acceptance_cases and research_jobs</td></tr>
<tr><td>mcp_calls</td><td>call_id, at, principal, tool, args_digest, args_size, result_size, duration_ms, outcome, error_code, downstream_request_ids, request_id</td><td>Insert-only audit of every MCP call</td></tr>
<tr><td>deliveries</td><td>delivery_id, deliverable_id, job_id, fetched_at, exported_path, export_sha256</td><td>Insert-only</td></tr>
<tr><td>setup_state</td><td>state_id, at, step (pool, providers, data, token), status, details</td><td>Insert-only; the latest row per step is current</td></tr>
</tbody>
</table>
</div>

<h3 id="s-16-5"><span class="sn">16.5</span>Registry API (registry-api)</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Method</th><th>Path</th><th>Roles</th><th>Behavior</th></tr></thead>
<tbody>
<tr><td>POST</td><td>/v1/artifacts</td><td>Publisher, control (seeds only)</td><td>Publish. The body holds the manifest and a client publish_key for retry safety. The service validates the schema, checks declared fields against the parsed expression, computes hashes server-side, assigns family and version, and records parents with AST diffs. Returns 201 for a new version, or 200 with the existing version for identical content</td></tr>
<tr><td>GET</td><td>/v1/artifacts/{version_id}</td><td>Reader, evaluator, publisher, control</td><td>Manifest plus server fields</td></tr>
<tr><td>GET</td><td>/v1/artifacts?since_seq=&amp;limit=</td><td>Evaluator, reader, control</td><td>Versions ordered by published_seq</td></tr>
<tr><td>GET</td><td>/v1/families/{family_id}</td><td>Any role</td><td>Family plus its versions</td></tr>
<tr><td>GET</td><td>/v1/artifacts/{version_id}/lineage?depth=</td><td>Any role</td><td>Parents and children with AST diffs</td></tr>
<tr><td>GET</td><td>/v1/pools/{pool}</td><td>Any role</td><td>Current pool entries (pool_current_v)</td></tr>
<tr><td>GET</td><td>/v1/pools/{pool}/events?since_seq=&amp;limit=</td><td>Evaluator, reader, control</td><td>Pool events ordered by event_seq</td></tr>
<tr><td>POST</td><td>/v1/pools/{pool}/entries</td><td>Control only</td><td>Add an entry: version must exist, kind must match the pool, approval_id required except for seed imports which carry the setup reference. Writes the ADDED event</td></tr>
<tr><td>POST</td><td>/v1/pools/{pool}/entries/{entry_id}/events</td><td>Control only</td><td>Append STATUS_CHANGED (approval_id required) or ANNOTATED</td></tr>
<tr><td>GET</td><td>/healthz</td><td>None</td><td>Liveness</td></tr>
</tbody>
</table>
</div>
<p>Errors: 400 with field-level validation messages, 401 or 403 for authentication and authorization, 409 when the kind conflicts with the family or the pool. There are no PUT, PATCH or DELETE routes (test REG-01 covers the database, BND-09 the OpenAPI document).</p>

<h3 id="s-16-6"><span class="sn">16.6</span>Feedback API (feedback-api, GET only)</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Method</th><th>Path</th><th>Behavior</th></tr></thead>
<tbody>
<tr><td>GET</td><td>/v1/reports?after_id=&amp;since=&amp;version_id=&amp;family_id=&amp;type=&amp;limit=</td><td>Released reports in release order for the token's programs</td></tr>
<tr><td>GET</td><td>/v1/reports/{report_id}</td><td>One released report</td></tr>
<tr><td>GET</td><td>/v1/artifacts/{version_id}/status</td><td>Latest released state and the released timeline</td></tr>
<tr><td>GET</td><td>/v1/library</td><td>Library version ids and statuses</td></tr>
<tr><td>GET</td><td>/v1/cards/policy, /v1/cards/protocol</td><td>Public cards</td></tr>
<tr><td>GET</td><td>/healthz</td><td>Liveness</td></tr>
</tbody>
</table>
</div>
<p>Test BND-03 asserts that the generated OpenAPI document contains only GET operations.</p>

<h3 id="s-16-7"><span class="sn">16.7</span>Research control API (research-api, called only by qfr-mcp)</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Method</th><th>Path</th><th>Behavior</th></tr></thead>
<tbody>
<tr><td>POST</td><td>/v1/jobs</td><td>Validate a brief, run the owner-only scan, publish seeds, derive the charter, create and start the program; returns the job with its timeline estimate</td></tr>
<tr><td>GET</td><td>/v1/jobs, /v1/jobs/{id}, /v1/jobs/{id}/events?after_seq=</td><td>Jobs, details and events</td></tr>
<tr><td>GET</td><td>/v1/jobs/{id}/wait?timeout_s=</td><td>Long-poll for a state change</td></tr>
<tr><td>POST</td><td>/v1/jobs/{id}/steer, pause, resume, cancel</td><td>Steering notes (scanned) and control</td></tr>
<tr><td>POST</td><td>/v1/jobs/{id}/close</td><td>Close with decision and approval_id</td></tr>
<tr><td>GET</td><td>/v1/jobs/{id}/deliverables, /v1/deliverables/{id}</td><td>Deliverables with iteration histories and released reports (no owner-grade evidence; qfr-mcp adds it)</td></tr>
<tr><td>GET</td><td>/v1/programs/{id}/generations, /v1/generations/{gid}, /v1/programs/{id}/population?island=, /v1/programs/{id}/archive</td><td>Research views</td></tr>
<tr><td>GET</td><td>/v1/hypotheses, /v1/candidates/{id}, /v1/interpretations</td><td>Blackboard entities</td></tr>
<tr><td>GET</td><td>/v1/trace/{version_id}, /v1/trace/candidates/{candidate_id}, /v1/trace/{version_id}/export</td><td>Trace steps with agent runs; canonical export</td></tr>
<tr><td>GET</td><td>/v1/lineage/{version_id}</td><td>Trajectory view</td></tr>
<tr><td>GET</td><td>/v1/costs?from=&amp;to=&amp;group_by=</td><td>Cost ledger aggregates</td></tr>
<tr><td>POST</td><td>/v1/programs/pause_all, /v1/programs/resume_all</td><td>Incident control</td></tr>
</tbody>
</table>
</div>
<p>None of these routes reaches the evaluation zone. The research control API reads the blackboard and cached released reports only, and it accepts only the control token.</p>

<h3 id="s-16-8"><span class="sn">16.8</span>Eval admin API (eval-admin-api, called only by qfr-mcp)</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Method</th><th>Path</th><th>Behavior</th></tr></thead>
<tbody>
<tr><td>POST</td><td>/v1/protocols, /v1/policies, /v1/quotas and /{id}/{version}/activate</td><td>Create and activate versions; activation records the approval id when policy says one is required</td></tr>
<tr><td>GET</td><td>/v1/intake, /v1/runs, /v1/records/{version_id}</td><td>Operations and official records</td></tr>
<tr><td>GET</td><td>/v1/evidence/{version_id}</td><td>Owner-grade evidence: official records on every window, gate values, series file refs, simulation state, library correlations. Labelled owner_only</td></tr>
<tr><td>GET</td><td>/v1/series/{run_id}/{kind}</td><td>Series file download for exports</td></tr>
<tr><td>GET</td><td>/v1/burn, /v1/quotas/usage</td><td>Burn meters and quota usage</td></tr>
<tr><td>GET</td><td>/v1/library</td><td>Library with effective dates</td></tr>
<tr><td>GET</td><td>/v1/sim/{sim_id}</td><td>Simulation state and NAV</td></tr>
<tr><td>GET</td><td>/v1/acceptance/cases</td><td>Open and decided cases with gate values</td></tr>
<tr><td>POST</td><td>/v1/acceptance/cases/{id}/decision</td><td>Decision plus a mandatory rationale and approval_id</td></tr>
<tr><td>GET, POST</td><td>/v1/alerts, /v1/alerts/{id}/acknowledge</td><td>Alerts</td></tr>
<tr><td>GET</td><td>/v1/config/private</td><td>Window dates and private gates for qfr.config.get owner_only</td></tr>
<tr><td>POST</td><td>/v1/epochs/rollover</td><td>Phase 8, approval_id required</td></tr>
</tbody>
</table>
</div>

<h3 id="s-16-9"><span class="sn">16.9</span>Authentication</h3>
<ul>
  <li>v1 uses static bearer tokens per principal, supplied through environment variables and mapped to roles: publisher, reader, evaluator and control for the registry; feedback reader; research control; eval owner; and the owner's MCP token.</li>
  <li>Every request logs the principal and a request id, and every write emits an audit event.</li>
  <li>All ports except the MCP front door are reachable only on the compose networks. Phase 8 <span class="kw">MAY</span> add mutual TLS between services; v1 relies on network separation on a single host.</li>
</ul>
</section>
<!-- ===================================================== CHAPTER 17 -->
<section class="chapter" id="ch-17">
<div class="chapter-kicker"><span class="n">17</span>Chapter 17</div>
<h2>Security, operations and deployment on the Mac Studio<a class="anchor" href="#ch-17">#</a></h2>

<h3 id="s-17-1"><span class="sn">17.1</span>Threat model</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Threat</th><th>Example</th><th>Defense</th></tr></thead>
<tbody>
<tr><td>Evaluation gaming</td><td>A factor behaves differently on evaluation periods</td><td>The DSL has no access to dates or identifiers. Computation is one pass over the full history. A prefix-invariance probe runs at screening</td></tr>
<tr><td>Covert channels</td><td>Holdout information encoded into errors or timings</td><td>Only sanitized enum codes are released. No timings or free text. The Python sandbox (Phase 8) has no network</td></tr>
<tr><td>Adaptive overfitting</td><td>Sequential probing of W1 or W2</td><td>Coarsening, quotas, the Ladder, burn meters, and a trial ledger feeding DSR and PBO</td></tr>
<tr><td>LLM memorization</td><td>Factors designed around remembered market episodes</td><td>No tickers or dates in the DSL or prompts. The critic flags period-specific narratives. Forward incubation is required for the top tier, and every deliverable states its tier</td></tr>
<tr><td>Leakage through the owner channel</td><td>Owner-only numbers pasted into a brief</td><td>Evidence objects cannot be attached to briefs; briefs and steering notes are scanned for owner-only values; the host-agent guide forbids it; residual risk accepted and recorded</td></tr>
<tr><td>Host agent overreach</td><td>The host agent approves or curates without the owner saying so</td><td>Approval records quote the owner and must contain the scope's short codes; every call is audited; the catalog has no research or evaluation powers (MCP-02)</td></tr>
<tr><td>Token theft on the Mac</td><td>Another process on the Mac reads the MCP token</td><td>Loopback-only bind; token in a 0600 file; rotation command; the token grants owner powers but never LLM keys or database access; audit makes misuse visible</td></tr>
<tr><td>Boundary erosion</td><td>A developer adds a convenience endpoint that crosses zones</td><td>Invariant tests in CI, import-linter contracts, snapshot tests of the tool registry and the MCP catalog</td></tr>
<tr><td>Silent mutation</td><td>Editing a published artifact, record, trace step or approval</td><td>Triggers, grants, and server-computed hashes</td></tr>
<tr><td>Research-zone leakage</td><td>Research reads post-cutoff data or evaluation logs</td><td>Physically truncated snapshot; no eval or control log mounts in research containers; tests on mounts and on the maximum date</td></tr>
<tr><td>Cost runaway</td><td>An agent loops on tool calls, or a provider misprices</td><td>Per-run usage limits, generation, daily and job caps, a hard stop, and refusal to run unpriced models</td></tr>
<tr><td>Provider outage or drift</td><td>A provider is down or changes its API</td><td>Fallback chains, retries with backoff, the probe at setup, one adapter to patch</td></tr>
<tr><td>Prompt injection through feedback</td><td>Malicious text reaches prompts through reports</td><td>Reports are structured JSON with numbers and enum codes only. No evaluator free text reaches prompts. Owner notes in briefs are the owner's own text</td></tr>
</tbody>
</table>
</div>

<h3 id="s-17-2"><span class="sn">17.2</span>Deployment target and Docker Compose topology</h3>
<p>The target is a single <strong>Apple silicon Mac Studio</strong> running macOS, with Docker Desktop for Mac (OrbStack is an acceptable alternative with the same Compose file). Every image is built for <code>linux/arm64</code> and runs natively in the Docker VM; <code>linux/amd64</code> images are built in CI only. No process of QFR runs directly on macOS except the owner's commands and the optional stdio launcher.</p>

<figure id="fig-5">
<svg viewBox="0 0 1240 720" role="img" aria-labelledby="fig5-title">
<title id="fig5-title">Figure 5. Deployment topology on the Mac Studio: host agent, Docker Desktop VM with compose networks, volumes and bind mounts, and the two external endpoints</title>
<g class="host"><rect x="20" y="20" width="990" height="680"/><text x="40" y="50">Mac Studio · Apple silicon · macOS</text><text class="elabel" x="40" y="68" style="font-size:11px">Docker Desktop (or OrbStack) · sleep disabled · TZ Asia/Shanghai · only 127.0.0.1:8765 is published</text></g>

<g class="ext"><rect x="40" y="130" width="260" height="70"/><text x="170" y="158" text-anchor="middle">Host agent</text><text class="sub" x="170" y="176" text-anchor="middle">Codex · Claude Code · other MCP client</text><text class="sub" x="170" y="190" text-anchor="middle">http://127.0.0.1:8765/mcp + bearer token</text></g>
<g class="svc"><rect x="40" y="230" width="260" height="50"/><text x="170" y="251" text-anchor="middle">Owner's terminal</text><text class="sub" x="170" y="267" text-anchor="middle">just up · setup · doctor · logs · mcp-config · backup</text></g>
<g class="vol"><rect x="40" y="610" width="260" height="60"/><text x="170" y="634" text-anchor="middle">~/qfr/imports · exports · backups</text><text class="sub" x="170" y="652" text-anchor="middle" style="font-size:10px;fill:var(--muted)">owner-facing folders, bind-mounted into the VM</text></g>

<g class="vm"><rect x="330" y="80" width="650" height="600"/><text x="350" y="106">Docker Desktop VM · Docker Compose v2 · linux/arm64 images · one postgres, four databases</text></g>

<g class="net control"><rect x="350" y="124" width="610" height="76"/><text x="362" y="144">control_net</text></g>
<g class="svc"><rect x="370" y="154" width="220" height="40"/><text x="480" y="171" text-anchor="middle">qfr-mcp</text><text class="sub" x="480" y="186" text-anchor="middle">publishes 127.0.0.1:8765 → 8765</text></g>
<text class="elabel" x="610" y="178" text-anchor="start">control_db role · tokens for the three APIs · reads the logs volume</text>

<g class="net research"><rect x="350" y="226" width="300" height="120"/><text x="362" y="246">research_net · egress to providers only</text></g>
<g class="svc"><rect x="370" y="262" width="120" height="36"/><text x="430" y="284" text-anchor="middle">research-api</text></g>
<g class="svc"><rect x="500" y="262" width="135" height="36"/><text x="567" y="284" text-anchor="middle">research-worker</text></g>
<text class="elabel" x="500" y="318" text-anchor="middle">research_db · research snapshot ro</text>
<text class="elabel" x="500" y="334" text-anchor="middle">LLM keys live only in research-worker</text>

<g class="net registry"><rect x="665" y="226" width="295" height="60"/><text x="677" y="262">registry_net</text></g>
<g class="svc"><rect x="820" y="238" width="130" height="36"/><text x="885" y="260" text-anchor="middle">registry-api</text></g>

<g class="net eval"><rect x="665" y="296" width="295" height="180"/><text x="677" y="316">eval_net · internal · no egress</text></g>
<g class="svc"><rect x="680" y="330" width="85" height="30"/><text x="722" y="349" text-anchor="middle">eval-scheduler</text></g>
<g class="svc"><rect x="775" y="330" width="85" height="30"/><text x="817" y="349" text-anchor="middle">eval-worker ×2</text></g>
<g class="svc"><rect x="870" y="330" width="85" height="30"/><text x="912" y="349" text-anchor="middle">release-worker</text></g>
<g class="svc"><rect x="680" y="372" width="85" height="30"/><text x="722" y="391" text-anchor="middle">sim-engine</text></g>
<g class="svc"><rect x="775" y="372" width="85" height="30"/><text x="817" y="391" text-anchor="middle">feedback-api</text></g>
<g class="svc"><rect x="870" y="372" width="85" height="30"/><text x="912" y="391" text-anchor="middle">eval-admin-api</text></g>
<g class="svc"><rect x="680" y="414" width="85" height="30"/><text x="722" y="433" text-anchor="middle">data-ingest</text></g>
<text class="elabel" x="775" y="462" text-anchor="start">eval_db · full snapshot ro · no LLM keys anywhere here</text>

<g class="vm"><rect x="350" y="356" width="300" height="120"/><text x="362" y="376">postgres:16 · roles per zone · insert-only triggers</text></g>
<g class="svc"><rect x="370" y="386" width="130" height="32"/><text x="435" y="406" text-anchor="middle">research_db</text></g>
<g class="svc"><rect x="510" y="386" width="130" height="32"/><text x="575" y="406" text-anchor="middle">registry_db</text></g>
<g class="svc"><rect x="370" y="428" width="130" height="32"/><text x="435" y="448" text-anchor="middle">eval_db</text></g>
<g class="svc"><rect x="510" y="428" width="130" height="32"/><text x="575" y="448" text-anchor="middle">control_db</text></g>

<g class="vm"><rect x="350" y="492" width="610" height="90"/><text x="362" y="512">named volumes</text></g>
<g class="vol"><rect x="370" y="524" width="130" height="44"/><text x="435" y="542" text-anchor="middle">pg_data</text><text class="sub" x="435" y="558" text-anchor="middle" style="font-size:10px;fill:var(--muted)">postgres only</text></g>
<g class="vol"><rect x="510" y="524" width="130" height="44"/><text x="575" y="542" text-anchor="middle">snapshots_full</text><text class="sub" x="575" y="558" text-anchor="middle" style="font-size:10px;fill:var(--muted)">eval zone only</text></g>
<g class="vol"><rect x="650" y="524" width="140" height="44"/><text x="720" y="542" text-anchor="middle">snapshots_research</text><text class="sub" x="720" y="558" text-anchor="middle" style="font-size:10px;fill:var(--muted)">research zone only</text></g>
<g class="vol"><rect x="800" y="524" width="150" height="44"/><text x="875" y="542" text-anchor="middle">qfr_logs</text><text class="sub" x="875" y="558" text-anchor="middle" style="font-size:10px;fill:var(--muted)">own dir rw · qfr-mcp ro</text></g>

<g class="vm"><rect x="350" y="596" width="610" height="72"/><text x="362" y="616">bind mounts from ~/qfr</text></g>
<g class="vol"><rect x="370" y="626" width="130" height="34"/><text x="435" y="648" text-anchor="middle">imports (ro)</text></g>
<g class="vol"><rect x="510" y="626" width="130" height="34"/><text x="575" y="648" text-anchor="middle">exports (rw)</text></g>
<g class="vol"><rect x="650" y="626" width="130" height="34"/><text x="715" y="648" text-anchor="middle">backups (rw)</text></g>

<path class="edge both" d="M300,165 L370,174"/>
<text class="elabel strong" x="335" y="152" text-anchor="middle">MCP · loopback</text>
<path class="edge dashed" d="M300,255 L330,255"/>
<path class="edge dashed both" d="M300,640 L370,643"/>

<g class="ext"><rect x="1030" y="240" width="190" height="76"/><text x="1125" y="266" text-anchor="middle">LLM providers</text><text class="sub" x="1125" y="284" text-anchor="middle">Kimi · GLM · DeepSeek</text><text class="sub" x="1125" y="300" text-anchor="middle">HTTPS, OpenAI-compatible</text></g>
<g class="ext"><rect x="1030" y="420" width="190" height="76"/><text x="1125" y="446" text-anchor="middle">Market data source</text><text class="sub" x="1125" y="464" text-anchor="middle">chenditc/investment_data</text><text class="sub" x="1125" y="480" text-anchor="middle">GitHub releases, HTTPS</text></g>
<path class="edge" d="M567,262 V214 H1000 V278 H1030"/>
<text class="elabel" x="800" y="209" text-anchor="middle">egress: research-worker only</text>
<path class="edge" d="M765,429 H1000 V458 H1030"/>
<text class="elabel" x="880" y="424" text-anchor="middle">egress: data-ingest only</text>
</svg>
<figcaption><b>Figure 5. Deployment on the Mac Studio.</b> Four compose networks separate the zones; only <code>qfr-mcp</code> publishes a port, and only on loopback. The research worker is the sole holder of LLM keys and the sole path to the providers; data ingest is the sole path to the data source. Snapshots are separate volumes per zone, and the logs volume is written per service and read whole by the front door.</figcaption>
</figure>

<div class="table-wrap compact">
<table>
<thead><tr><th>Element</th><th>Definition</th></tr></thead>
<tbody>
<tr><td>Networks</td><td><code>control_net</code> (qfr-mcp with research-api, registry-api, eval-admin-api, feedback-api), <code>research_net</code> (research-api, research-worker, registry-api, feedback-api, postgres; egress allowed), <code>registry_net</code> (registry-api, postgres, plus the clients that need it), <code>eval_net</code> (<code>internal: true</code>; all evaluation services and postgres), <code>ingest_egress_net</code> (data-ingest only, egress allowed). Services join only the networks they need</td></tr>
<tr><td>Published ports</td><td><code>127.0.0.1:8765:8765</code> for qfr-mcp. Nothing else. A debugging override file may publish registry-api and feedback-api on loopback for development only</td></tr>
<tr><td>Named volumes</td><td><code>pg_data</code>, <code>snapshots_full</code> (evaluation services, read-only except data-ingest), <code>snapshots_research</code> (research services, read-only; data-ingest writes it), <code>qfr_logs</code> (each service its own subdirectory read-write, qfr-mcp read-only)</td></tr>
<tr><td>Bind mounts</td><td><code>~/qfr/imports</code> (qfr-mcp and setup, read-only), <code>~/qfr/exports</code> (qfr-mcp, read-write), <code>~/qfr/backups</code> (backup job, read-write). Named volumes are used for data and databases because bind mounts are slower on macOS</td></tr>
<tr><td>Resource limits</td><td>Compose <code>deploy.resources.limits</code>: eval-worker 4 CPU and 6 GB each, 2 replicas by default; research-worker 2 CPU and 4 GB; postgres 4 CPU and 8 GB; others 1 CPU and 1 GB. Docker Desktop itself: at least 8 CPUs, 24 GB memory and 200 GB disk assigned to the VM; VirtioFS file sharing; Rosetta emulation off because every image is native</td></tr>
<tr><td>Hardening</td><td>Every container runs as a non-root user with <code>read_only: true</code> root filesystem, <code>cap_drop: [ALL]</code>, <code>no-new-privileges</code>, tmpfs for scratch, and health checks. gVisor is not available on Docker Desktop for Mac; the Phase 8 Python sandbox therefore relies on these controls plus <code>network_mode: none</code>, and v1 executes no artifact code at all</td></tr>
<tr><td>Images</td><td>One multi-stage Dockerfile; base <code>python:3.12-slim</code> (multi-arch); dependencies from <code>uv.lock</code>; <code>docker buildx</code> targets linux/arm64 locally and both platforms in CI; image digests recorded per platform and pinned in official records</td></tr>
<tr><td>Time and power</td><td><code>TZ=Asia/Shanghai</code> in every container; the daily cycle follows the CN trading calendar; macOS sleep disabled (Energy settings or <code>caffeinate</code>); Docker Desktop starts at login; NTP on</td></tr>
</tbody>
</table>
</div>

<h3 id="s-17-3"><span class="sn">17.3</span>Installation and setup</h3>
<ol>
  <li><strong>Prepare the Mac.</strong> Install Docker Desktop for Mac (Apple silicon build) and assign CPUs, memory and disk as above. Install <code>just</code> and <code>uv</code> (Homebrew). Disable sleep. Create <code>~/qfr/imports</code>, <code>~/qfr/exports</code>, <code>~/qfr/backups</code>.</li>
  <li><strong>Clone and configure.</strong> Clone the repository. Run <code>just init-secrets</code>, which generates every internal token and the owner's MCP token into <code>.env</code> (mode 0600). Add the three provider keys to <code>.env</code> by hand.</li>
  <li><strong>Build and start.</strong> <code>just build</code> builds linux/arm64 images locally. <code>just up</code> starts postgres, runs migrations, starts every service and waits for health checks.</li>
  <li><strong>Setup.</strong> <code>just setup</code> asks the four questions of <a href="#s-13-6">Section 13.6</a>: raw factor pool (or none), provider probe, data source and first ingest, token and host-agent configuration. Everything it does is also reachable through MCP, so the owner may instead connect the host agent first and let it drive setup conversationally.</li>
  <li><strong>Connect the host agent.</strong> Paste the snippet from <code>just mcp-config</code> into Claude Code, Codex or another client. Ask the host agent to call <code>qfr.status</code>.</li>
  <li><strong>Check the deployment.</strong> <code>just doctor</code> verifies: native arm64 containers, all health checks green, four databases and five roles, boundary tests BND-01 and BND-06 to BND-09 against the running stack, only loopback ports published, time zone, disk headroom, log volume writable by each service and readable by qfr-mcp. Its report is written to <code>exports/doctor/</code> and logged. SC12 is met when it passes.</li>
</ol>

<h3 id="s-17-4"><span class="sn">17.4</span>Operations runbook</h3>
<ul>
  <li><strong>Daily (Asia/Shanghai):</strong> 18:30 data ingest and full snapshot build; then the simulation cycle.</li>
  <li><strong>Continuous:</strong> the evaluator releases each report as soon as it records it, and a running job starts its next generation when the previous generation's feedback is complete.</li>
  <li><strong>Nightly (02:30):</strong> fingerprints and trial clustering for N_eff, burn meters, log compression and retention, disk guard, backups (<a href="#s-17-5">Section 17.5</a>).</li>
  <li><strong>Reproduce a result:</strong> <code>qfr eval reproduce &lt;record_id&gt;</code> re-runs with pinned inputs and compares the results hash.</li>
  <li><strong>Boundary incident:</strong> if any boundary test fails against the deployed stack (<code>just doctor</code> runs them), pause all research programs with <code>qfr.ops.pause_research</code> until it is fixed and documented in <code>docs/decisions.md</code>.</li>
  <li><strong>Data staleness:</strong> if no new data arrives for 2 trading days, simulation clocks pause and an alert appears in <code>qfr.ops.alerts</code> and <code>qfr.status</code>.</li>
  <li><strong>Provider incident:</strong> fallback chains keep research running; repeated fallbacks raise an alert; the owner may reorder chains in <code>roles.yaml</code> and restart research-worker.</li>
  <li><strong>Updates:</strong> pull, <code>just build</code>, <code>just up</code>. Migrations run in the one-shot migrate service before services start. Official records stay reproducible because they pin image digests; <code>qfr eval reproduce</code> on an old record pulls the old image by digest.</li>
  <li><strong>Watching:</strong> <code>qfr.status</code> for the summary, <code>qfr.logs.tail</code> for live activity, <code>docker compose logs -f</code> on the Mac when the front door itself is in question.</li>
</ul>

<h3 id="s-17-5"><span class="sn">17.5</span>Backups and recovery</h3>
<ul>
  <li>Nightly <code>pg_dump</code> of each of the four databases into <code>~/qfr/backups/&lt;date&gt;/</code>, compressed, with SHA-256 sums. Retention 30 daily and 12 monthly dumps.</li>
  <li>Snapshots are content-addressed directories; the nightly job mirrors <code>snapshots_full</code> and <code>snapshots_research</code> into <code>~/qfr/backups/snapshots/</code> with rsync. Raw downloads are not backed up; they can be fetched again by release tag.</li>
  <li>The logs volume is compressed in place and included in the monthly backup only.</li>
  <li><code>~/qfr/backups</code> should live on an external or cloud-synced disk; the Docker VM disk image should be excluded from Time Machine.</li>
  <li><strong>Restore drill:</strong> <code>just restore-drill</code> restores the latest dumps into a throwaway compose project and runs BND-01, REG-01 and EVL-04 on it. The owner runs it quarterly; the result is logged and exported.</li>
</ul>
</section>
<!-- ===================================================== CHAPTER 18 -->
<section class="chapter" id="ch-18">
<div class="chapter-kicker"><span class="n">18</span>Chapter 18</div>
<h2>Testing strategy and benchmarks<a class="anchor" href="#ch-18">#</a></h2>

<h3 id="s-18-1"><span class="sn">18.1</span>Test layers</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Layer</th><th>Scope</th></tr></thead>
<tbody>
<tr><td>Unit</td><td>Each DSL operator against its naive reference implementation on random panels. Metrics against hand-computed fixtures. PSR, DSR and PBO against worked examples. Trace completeness rules. Redaction patterns</td></tr>
<tr><td>Property-based</td><td>Using hypothesis: random valid DSL expressions satisfy prefix invariance. Canonicalization is idempotent and invariant to reordering commutative children. Parsing round-trips. AST diff applied to the parent reproduces the child</td></tr>
<tr><td>Integration</td><td>Registry API with its database, including pool routes. The evaluation pipeline on a synthetic snapshot. The release engine schedules. Feedback sync. The MCP server against the three APIs with scripted responses</td></tr>
<tr><td>End to end</td><td>The whole loop with a scripted LLM (PydanticAI FunctionModel) on synthetic worlds, driven through the MCP front door by a scripted MCP client, with real model requests forbidden</td></tr>
<tr><td>Boundary and security</td><td>Run in CI against a real Postgres with the production role setup, and on the Mac by <code>just doctor</code> against the running compose stack</td></tr>
<tr><td>Benchmarks</td><td>Nightly planted, null and decay worlds</td></tr>
<tr><td>Manual, owner-authorized</td><td>Real-provider smoke runs and the host-agent rehearsal (SC8) on the Mac Studio</td></tr>
</tbody>
</table>
</div>

<h3 id="s-18-2"><span class="sn">18.2</span>Named test suites</h3>
<p>These IDs are referenced by the invariants in <a href="#ch-3">Section 3</a> and the acceptance checks in <a href="#ch-19">Section 19</a>.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th class="id">ID</th><th>Test</th></tr></thead>
<tbody>
<tr><td class="id">BND-01</td><td>The research database role cannot connect to eval_db or control_db, the eval role cannot connect to research_db or control_db, and the control role cannot connect to any other database</td></tr>
<tr><td class="id">BND-02</td><td>A snapshot test of the research tool registry contains no tool that can affect evaluation, pools or jobs</td></tr>
<tr><td class="id">BND-03</td><td>The Feedback API OpenAPI document contains only GET operations, and its responses come only from released reports</td></tr>
<tr><td class="id">BND-04</td><td>import-linter contracts pass, including qfr_mcp importing only qfr_core</td></tr>
<tr><td class="id">BND-05</td><td>Research configuration contains no evaluation-admin or control URL or token, and the research services make no outbound calls to evaluation or control services</td></tr>
<tr><td class="id">BND-06</td><td>The research snapshot's maximum date is on or before the cutoff, and research containers have no full-snapshot mount (compose configuration test)</td></tr>
<tr><td class="id">BND-07</td><td>No container other than research-worker has any provider key variable set (compose configuration test and a runtime check in every service's startup)</td></tr>
<tr><td class="id">BND-08</td><td>Research containers mount no evaluation or control log directory; qfr-mcp mounts the logs volume read-only</td></tr>
<tr><td class="id">BND-09</td><td>The Registry API OpenAPI document contains no mutation route other than POST /v1/artifacts and the two pool POST routes, and the pool routes reject every token but control</td></tr>
<tr><td class="id">REG-01</td><td>UPDATE and DELETE on artifact_versions, pool_entries and pool_events raise at the database level, even as registry_app</td></tr>
<tr><td class="id">REG-02</td><td>Republishing identical content returns the same version id</td></tr>
<tr><td class="id">REG-03</td><td>Any manifest change produces a new version_no and content_hash</td></tr>
<tr><td class="id">REG-04</td><td>The server recomputes content_hash and ignores any client-supplied hash</td></tr>
<tr><td class="id">EVL-01</td><td>The evaluator discovers versions and pool changes only through since_seq polling, and no inbound trigger endpoint exists</td></tr>
<tr><td class="id">EVL-02</td><td>Every official record and released report has non-null references to version id, content hash, protocol, snapshot and code version</td></tr>
<tr><td class="id">EVL-03</td><td>The prefix-invariance probe catches an injected test-only lookahead operator</td></tr>
<tr><td class="id">EVL-04</td><td>Re-running an official record reproduces its results hash</td></tr>
<tr><td class="id">EVL-05</td><td>Exact and behavioral duplicates are never evaluated or counted as trials</td></tr>
<tr><td class="id">EVL-06</td><td>A trial-ledger row exists for every version evaluated on W1, W2 or W3</td></tr>
<tr><td class="id">REL-01</td><td>W1 values are rounded to the policy granularity</td></tr>
<tr><td class="id">REL-02</td><td>A report is released as soon as its decision is recorded, within one release-engine tick, in queue order (intake, screening, W1)</td></tr>
<tr><td class="id">REL-03</td><td>Quotas defer excess intake, and deferrals expire after 7 days</td></tr>
<tr><td class="id">REL-04</td><td>Every released report validates against the public JSON schema, which contains only whitelisted fields and enum codes</td></tr>
<tr><td class="id">REL-05</td><td>No released report contains any W3-derived field. This is a scan test, plus a property test over random policies</td></tr>
<tr><td class="id">REL-06</td><td>The Ladder releases a new family best only when it improves by at least η</td></tr>
<tr><td class="id">ACC-01</td><td>DSR uses N_eff computed from the trial ledger</td></tr>
<tr><td class="id">ACC-02</td><td>No acceptance case can be opened before incubation completes</td></tr>
<tr><td class="id">ACC-03</td><td>No code path sets a library or pool entry to an approved status, and no acceptance case closes as accepted, without an approval record</td></tr>
<tr><td class="id">POOL-01</td><td>Pool entries and status events require a valid approval id whose scope covers the version (seed imports excepted), reject research and evaluator tokens, and produce events and audit rows</td></tr>
<tr><td class="id">AUD-01</td><td>Every write produces an audit event with a principal and a request id</td></tr>
<tr><td class="id">MCP-01</td><td>Every MCP call produces an mcp_calls row and a log line with a request id that appears in the downstream service's logs</td></tr>
<tr><td class="id">MCP-02</td><td>A snapshot test of the MCP tool catalog: no tool publishes artifacts, calls research tools, writes official records, alters runs or queues, or reads research-zone data files; approval-gated tools reject calls without a matching approval</td></tr>
<tr><td class="id">MCP-03</td><td>qfr.approval.record rejects a confirmation that lacks any short code in scope; qfr.job.submit and qfr.job.steer reject text containing owner-only values of referenced versions</td></tr>
<tr><td class="id">TRC-01</td><td>The packager refuses to publish a candidate whose trace lacks a required step for its operator, and records the refusal</td></tr>
<tr><td class="id">TRC-02</td><td>Every LLM step has an agent run with full request and response, and a log line with the same run id</td></tr>
<tr><td class="id">TRC-03</td><td>Every operator application has parents and an AST diff, and the iteration history reconstructs every hop of a five-generation synthetic lineage including one crossover</td></tr>
<tr><td class="id">LOG-01</td><td>Every service emits the mandatory fields on every line, and every line concerning an entity carries its id</td></tr>
<tr><td class="id">LOG-02</td><td>A fake provider key injected through configuration, a prompt and an exception message never appears in any sink</td></tr>
<tr><td class="id">LOG-03</td><td>For a synthetic end-to-end job, qfr.logs.correlate on the job id returns lines from qfr-mcp, research-api, research-worker, registry-api, eval-scheduler, eval-worker and release-worker, in time order</td></tr>
<tr><td class="id">LOG-04</td><td>Daily rotation, compression after 7 days and deletion after 180 days behave as configured on a synthetic directory</td></tr>
<tr><td class="id">SET-01</td><td>A fresh deployment without a raw pool has zero pool entries, zero versions and zero programs; a job submitted through MCP completes a generation from exploration alone; the library-correlation gate is recorded as vacuous</td></tr>
<tr><td class="id">SET-02</td><td>Importing a raw pool file publishes one human_seed version and one seed entry per valid row, reports invalid rows with reason codes, and is idempotent on re-import</td></tr>
<tr><td class="id">DEP-01</td><td><code>just doctor</code> on the Mac Studio: native arm64 containers, health, databases and roles, loopback-only ports, mounts, time zone, disk headroom, log volume permissions</td></tr>
</tbody>
</table>
</div>

<h3 id="s-18-3"><span class="sn">18.3</span>Benchmarks</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th class="id">ID</th><th>Setup</th><th>Pass condition</th></tr></thead>
<tbody>
<tr><td class="id">BM-PLANTED</td><td>Planted world. The scripted LLM draws from a pool of 300 expressions: variants of A1 and A2 at several windows plus many noise expressions. Incubation runs in replay mode. The job is submitted through the MCP front door by a scripted client</td><td>At least one accepted factor with mean rank correlation of 0.7 or more to A1 or A2 within 10 generations. Generations to discovery are recorded. The deliverable's iteration history reaches back to the explore hypothesis</td></tr>
<tr><td class="id">BM-NULL</td><td>Null world, same pool, 50 generations</td><td>Zero acceptances. The W1 pass rate and W2 pass count are recorded</td></tr>
<tr><td class="id">BM-DECAY</td><td>Decay world with an approved A3-like factor in the pool</td><td>A monitoring alert fires within 60 forward days after the switch-off and is visible in qfr.ops.alerts</td></tr>
<tr><td class="id">BM-STRATEGY</td><td>Planted world, mode new_strategy with A1 and A2 variants available</td><td>A strategy deliverable whose reference backtest beats the equal-weight benchmark on W1 and W2 with net Sharpe above the gate</td></tr>
<tr><td class="id">BM-REAL-SMOKE</td><td>CN data, real providers, 20 generations, run manually on the Mac Studio with owner authorization</td><td>No crashes, costs within caps, every report linked to the exact version it evaluated, every provider used at least once, fallbacks logged if any. A cost and stability report is exported</td></tr>
</tbody>
</table>
</div>
<p>Calibration rule: if BM-NULL accepts anything, the owner tightens the gates (a new protocol version through MCP) before any real-data campaign and records the change in <code>docs/decisions.md</code>. Benchmarks run nightly in CI with fixed seeds, and their results are stored as artifacts.</p>
</section>

<!-- ===================================================== CHAPTER 19 -->
<section class="chapter" id="ch-19">
<div class="chapter-kicker"><span class="n">19</span>Chapter 19</div>
<h2>Implementation roadmap<a class="anchor" href="#ch-19">#</a></h2>
<p class="lead">Nine phases, built in order. Each phase takes one or more coding-agent sessions. Do not start a phase until every acceptance check of the previous phase passes in CI and, where stated, on the Mac Studio. Tasks are checklist items so progress can be tracked; ticks are saved in this browser only.</p>

<div class="roadmap-glance">
  <a href="#ph-0">Phase 0 · Foundation, contracts, logging and the MCP skeleton<small>repository, compose on arm64, four databases, structlog, first MCP tools</small></a>
  <a href="#ph-1">Phase 1 · Data layer, DSL and metrics core<small>snapshots, synthetic worlds, Qlib reader, DSL, operators, metrics, statistics, backtester</small></a>
  <a href="#ph-2">Phase 2 · Artifact registry, pools and setup import<small>immutable versions, pool tables and routes, raw factor pool import, empty start</small></a>
  <a href="#ph-3">Phase 3 · Independent evaluation: intake, screening, W1, release and feedback<small>scheduler, library sync, official records, release engine, Feedback API, eval admin API</small></a>
  <a href="#ph-4">Phase 4 · Research system v1 and the owner workflow<small>providers, agents, workflow, jobs, deliverables, traces, MCP job tools</small></a>
  <a href="#ph-5">Phase 5 · Evolutionary engine<small>islands, archive, fitness, operators, bandit, traced variation</small></a>
  <a href="#ph-6">Phase 6 · Validation, holdout, simulated trading, acceptance and pools<small>W2, W3, simulation, strategies, approvals, pool curation, monitoring</small></a>
  <a href="#ph-7">Phase 7 · Operator experience through the MCP front door<small>exports, evidence views, operations tools, log search at scale, host-agent guide, rehearsal</small></a>
  <a href="#ph-8">Phase 8 · Hardening and extensions<small>Python sandbox, richer strategies, Thresholdout, epoch rollover, split databases, overrides</small></a>
</div>

<div class="progress" id="progress-top">
  <span>Implementation progress</span>
  <div class="bar"><span id="progress-bar"></span></div>
  <span class="num" id="progress-num">0/0</span>
  <button type="button" id="progress-reset">Reset progress</button>
</div>

<!-- ---------------- Phase 0 -->
<div class="phase" id="ph-0">
<div class="phase-head"><h3>Phase 0 · Foundation, contracts, logging and the MCP skeleton</h3><span class="count">9 tasks</span></div>
<p class="goal"><strong>Goal.</strong> The repository, tooling, infrastructure, logging and a boundary skeleton that later phases cannot accidentally break, plus a front door that already answers.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P0-1" data-task="P0.1"><label for="t-P0-1"><b>P0.1</b> Create the uv workspace with packages qfr_core, qfr_registry, qfr_research, qfr_eval and qfr_mcp. Configure ruff, mypy (strict for qfr_core and qfr_mcp), pytest and hypothesis, and add a justfile with check, test, build, up, down, setup, doctor, logs, mcp-config, backup and bench targets.</label></li>
<li><input type="checkbox" id="t-P0-2" data-task="P0.2"><label for="t-P0-2"><b>P0.2</b> Add the import-linter contracts from <a href="#s-5-3">Section 5.3</a>, including qfr_mcp importing only qfr_core, and wire them into the check target.</label></li>
<li><input type="checkbox" id="t-P0-3" data-task="P0.3"><label for="t-P0-3"><b>P0.3</b> Write the multi-arch Dockerfile and docker-compose.yml for the Mac Studio: Postgres 16 with init SQL creating research_db, registry_db, eval_db and control_db, the roles registry_app, research_rw, eval_rw, feedback_ro and control_rw, and the grants from <a href="#s-5-4">Section 5.4</a>; the networks, volumes, loopback-only port, hardening options and resource limits from <a href="#s-17-2">Section 17.2</a>; placeholder services that exit cleanly.</label></li>
<li><input type="checkbox" id="t-P0-4" data-task="P0.4"><label for="t-P0-4"><b>P0.4</b> Implement configuration loading (pydantic-settings plus YAML) for protocols, release policies, quotas, charters, providers, roles, epochs, logging and mcp, and commit the <a href="#ch-20">Section 20</a> defaults under configs/. No default factors or strategies anywhere.</label></li>
<li><input type="checkbox" id="t-P0-5" data-task="P0.5"><label for="t-P0-5"><b>P0.5</b> Define the public Pydantic schemas in qfr_core (factor and strategy manifests, released report, reason-code and flag enums, ResearchBrief, Deliverable, IterationHistory, TraceStep, ApprovalRecord, PoolEntry, pool import file, log line) and the private official-record and owner-evidence schemas in qfr_eval, with JSON Schema generation and one valid and one invalid example per contract.</label></li>
<li><input type="checkbox" id="t-P0-6" data-task="P0.6"><label for="t-P0-6"><b>P0.6</b> Implement the logging foundation from <a href="#ch-15">Section 15</a>: structlog JSON, mandatory fields, correlation-id propagation through contextvars, HTTP headers and queue payloads, stdout and per-service file sinks, rotation, the redaction processor, and the <code>qfr logs</code> CLI.</label></li>
<li><input type="checkbox" id="t-P0-7" data-task="P0.7"><label for="t-P0-7"><b>P0.7</b> Implement the MCP server skeleton: streamable HTTP on loopback with bearer-token authentication, the mcp_calls audit, and the tools qfr.status, qfr.config.get, qfr.logs.search, qfr.logs.tail and qfr.logs.correlate; <code>just mcp-config</code> prints client snippets.</label></li>
<li><input type="checkbox" id="t-P0-8" data-task="P0.8"><label for="t-P0-8"><b>P0.8</b> Set up CI (GitHub Actions) running lint, type checks, import-linter and tests against a Postgres service container, and building images for linux/arm64 and linux/amd64 with digests recorded.</label></li>
<li><input type="checkbox" id="t-P0-9" data-task="P0.9"><label for="t-P0-9"><b>P0.9</b> Add docs/PLAN.md (this document), docs/decisions.md and AGENTS.md (<a href="#s-21-1">Section 21.1</a>) to the repository.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>The check and test targets pass in CI, including both image builds.</li>
<li>On the Mac Studio, <code>just up</code> starts Postgres with all four databases and five roles; BND-01, BND-04, BND-07, BND-08 and DEP-01 pass.</li>
<li>LOG-01 and LOG-02 pass. A host agent connected through MCP can call qfr.status and qfr.logs.tail, and MCP-01 passes for those calls.</li>
</ul></div>
</div>

<!-- ---------------- Phase 1 -->
<div class="phase" id="ph-1">
<div class="phase-head"><h3>Phase 1 · Data layer, DSL and metrics core</h3><span class="count">11 tasks</span></div>
<p class="goal"><strong>Goal.</strong> Trustworthy data, a lookahead-safe factor language and exact metric definitions, shared by both zones.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P1-1" data-task="P1.1"><label for="t-P1-1"><b>P1.1</b> Implement the dense canonical panel format, the snapshot manifest and content-addressed snapshot ids (<a href="#s-6-3">Section 6.3</a>).</label></li>
<li><input type="checkbox" id="t-P1-2" data-task="P1.2"><label for="t-P1-2"><b>P1.2</b> Implement the synthetic market generator with planted, null and decay worlds, and calibrate each alpha to its target RankIC (<a href="#s-6-6">Section 6.6</a>).</label></li>
<li><input type="checkbox" id="t-P1-3" data-task="P1.3"><label for="t-P1-3"><b>P1.3</b> Implement the Qlib binary reader and CN ingest from investment_data releases: checksum validation, point-in-time membership, tradability flags, raw-price derivation and sanity checks (<a href="#s-6-2">Section 6.2</a>).</label></li>
<li><input type="checkbox" id="t-P1-4" data-task="P1.4"><label for="t-P1-4"><b>P1.4</b> Implement the zone builder, which writes a date-truncated research snapshot and a full snapshot, plus the CLI command <code>qfr data build</code> with source synthetic or cn.</label></li>
<li><input type="checkbox" id="t-P1-5" data-task="P1.5"><label for="t-P1-5"><b>P1.5</b> Implement the DSL: Lark grammar, type checker, static constraints, canonicalizer, canonical hash, complexity score, AST similarity and the deterministic AST diff (Sections <a href="#s-7-2">7.2</a> to <a href="#s-7-5">7.5</a>).</label></li>
<li><input type="checkbox" id="t-P1-6" data-task="P1.6"><label for="t-P1-6"><b>P1.6</b> Implement the operator library in Polars with the calendar-based validity rule, plus naive reference implementations for tests (<a href="#s-7-3">Section 7.3</a>).</label></li>
<li><input type="checkbox" id="t-P1-7" data-task="P1.7"><label for="t-P1-7"><b>P1.7</b> Implement the metrics library: preprocessing, IC, RankIC, IR, Newey–West t, decay, quantiles, long-short gross and net, turnover, autocorrelation, coverage, library correlation and behavioral fingerprints (<a href="#s-8-5">Section 8.5</a>).</label></li>
<li><input type="checkbox" id="t-P1-8" data-task="P1.8"><label for="t-P1-8"><b>P1.8</b> Implement PSR, DSR and PBO (CSCV) with tests against worked examples (<a href="#s-8-7">Section 8.7</a>).</label></li>
<li><input type="checkbox" id="t-P1-9" data-task="P1.9"><label for="t-P1-9"><b>P1.9</b> Implement the reference TopK-dropout backtester with tradability rules, costs and the per-component contribution table, plus hand-computed fixtures (<a href="#s-8-6">Section 8.6</a>).</label></li>
<li><input type="checkbox" id="t-P1-10" data-task="P1.10"><label for="t-P1-10"><b>P1.10</b> Implement the strategy composite: z-score weighted sum of factor panels with signs and normalized weights, and its canonical hash (<a href="#s-7-8">Section 7.8</a>).</label></li>
<li><input type="checkbox" id="t-P1-11" data-task="P1.11"><label for="t-P1-11"><b>P1.11</b> Implement the workbench facade that computes W0-only metrics for factors and composites on the research snapshot, using exactly the evaluator's definitions.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>Every operator matches its reference implementation, and prefix-invariance property tests pass for all operators.</li>
<li>On the planted world, the computed RankIC of A1 and A2 is within 0.005 of the calibrated target.</li>
<li>Hand-computed fixtures pass for metrics, PSR, DSR, PBO, the backtester and the composite.</li>
<li>BND-06 passes for a built research snapshot.</li>
</ul></div>
</div>

<!-- ---------------- Phase 2 -->
<div class="phase" id="ph-2">
<div class="phase-head"><h3>Phase 2 · Artifact registry, pools and setup import</h3><span class="count">6 tasks</span></div>
<p class="goal"><strong>Goal.</strong> Immutable, content-addressed, provenance-rich publication; owner-curated pools; a setup that asks for a raw factor pool and otherwise starts empty.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P2-1" data-task="P2.1"><label for="t-P2-1"><b>P2.1</b> Create the registry_db schema with Alembic: artifact tables, pool_entries, pool_events, the pool_current_v view, insert-only grants and triggers that block UPDATE and DELETE.</label></li>
<li><input type="checkbox" id="t-P2-2" data-task="P2.2"><label for="t-P2-2"><b>P2.2</b> Implement the publish endpoint: schema validation for factor and strategy manifests, declared-versus-parsed checks, server-side content and canonical hashes, family and version assignment, lineage parents with AST diffs, idempotency, and the human_seed operator.</label></li>
<li><input type="checkbox" id="t-P2-3" data-task="P2.3"><label for="t-P2-3"><b>P2.3</b> Implement the read endpoints, since_seq listing, lineage queries, pool listing and pool events since_seq (<a href="#s-16-5">Section 16.5</a>).</label></li>
<li><input type="checkbox" id="t-P2-4" data-task="P2.4"><label for="t-P2-4"><b>P2.4</b> Implement the pool write routes: add entry and append event, control token only, approval id required except for seed imports, kind-to-pool validation.</label></li>
<li><input type="checkbox" id="t-P2-5" data-task="P2.5"><label for="t-P2-5"><b>P2.5</b> Add role-based token authentication, request-id logging and registry audit events.</label></li>
<li><input type="checkbox" id="t-P2-6" data-task="P2.6"><label for="t-P2-6"><b>P2.6</b> Implement setup: the <code>qfr setup</code> CLI and the MCP tools qfr.setup.status, qfr.pool.import, qfr.pool.list, qfr.pool.get, qfr.dsl.validate and qfr.artifact.get; raw pool file parsing and validation; publication of seeds; the empty-start path with the no-defaults notice recorded in control_db.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>REG-01 to REG-04, BND-09, AUD-01 and POOL-01 pass.</li>
<li>SET-01 and SET-02 pass: a fresh stack is empty and says so; a 5-row sample file imported through MCP yields 5 human_seed versions and 5 seed entries, and an invalid row is rejected with a reason code and logged.</li>
</ul></div>
</div>

<!-- ---------------- Phase 3 -->
<div class="phase" id="ph-3">
<div class="phase-head"><h3>Phase 3 · Independent evaluation: intake, screening, W1, release and feedback</h3><span class="count">8 tasks</span></div>
<p class="goal"><strong>Goal.</strong> The measurement side works end to end on its own schedule; research can only read released results; the owner can read everything.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P3-1" data-task="P3.1"><label for="t-P3-1"><b>P3.1</b> Create the eval_db schema (<a href="#s-16-3">Section 16.3</a>) with Alembic, insert-only protections, feedback views, the library and pool_sync_cursor tables, and the Postgres job queue.</label></li>
<li><input type="checkbox" id="t-P3-2" data-task="P3.2"><label for="t-P3-2"><b>P3.2</b> Implement the scheduler: since_seq polling of versions and pool events, library sync, schema and kind checks, exact and behavioral dedup, quotas with deferral, and fair round-robin enqueueing.</label></li>
<li><input type="checkbox" id="t-P3-3" data-task="P3.3"><label for="t-P3-3"><b>P3.3</b> Implement screening: static constraints, single-pass computation, coverage, the prefix-invariance probe, runtime limits and degeneracy checks.</label></li>
<li><input type="checkbox" id="t-P3-4" data-task="P3.4"><label for="t-P3-4"><b>P3.4</b> Implement W1 evaluation runs that write runs, metrics, series files, official records and trial-ledger rows in a single transaction, with results hashes, through the factor plugin.</label></li>
<li><input type="checkbox" id="t-P3-5" data-task="P3.5"><label for="t-P3-5"><b>P3.5</b> Implement the release engine for the default_v1 intake, screening, W1 and library report types: whitelisted fields, rounding, immediate release, reason codes and diagnostic flags.</label></li>
<li><input type="checkbox" id="t-P3-6" data-task="P3.6"><label for="t-P3-6"><b>P3.6</b> Implement the read-only Feedback API with the policy and protocol cards.</label></li>
<li><input type="checkbox" id="t-P3-7" data-task="P3.7"><label for="t-P3-7"><b>P3.7</b> Implement the eval admin API for protocols, policies, quotas, intake, runs, records, owner-grade evidence, library and private config, plus the <code>qfr eval reproduce</code> command, and wire qfr.evidence.get, qfr.report.list and the qfr.ops.activate_* tools into the MCP server.</label></li>
<li><input type="checkbox" id="t-P3-8" data-task="P3.8"><label for="t-P3-8"><b>P3.8</b> Implement data-ingest scheduling and daily full-snapshot builds, with a synthetic daily-replay source for tests.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>End to end on the synthetic world: 30 seed factors imported through MCP are pulled, evaluated and released as soon as they are recorded, with rounded values, and their owner-grade evidence is readable through qfr.evidence.get at full precision.</li>
<li>EVL-01, EVL-02, EVL-04, EVL-05, EVL-06, REL-01 to REL-04 and BND-03 pass.</li>
<li>The seed entries become the correlation library once their W1 records exist, and a stack with no seeds records the library gate as vacuous.</li>
</ul></div>
</div>

<!-- ---------------- Phase 4 -->
<div class="phase" id="ph-4">
<div class="phase-head"><h3>Phase 4 · Research system v1 and the owner workflow</h3><span class="count">12 tasks</span></div>
<p class="goal"><strong>Goal.</strong> A brief submitted through MCP produces autonomous generations that publish reviewed candidates, learn from released reports, and hand the owner a traceable deliverable.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P4-1" data-task="P4.1"><label for="t-P4-1"><b>P4.1</b> Create the research_db schema (<a href="#s-16-2">Section 16.2</a>) with Alembic, including research_jobs, job_events, deliverables, trace_steps, agent_runs and the research job queue.</label></li>
<li><input type="checkbox" id="t-P4-2" data-task="P4.2"><label for="t-P4-2"><b>P4.2</b> Implement the provider layer (<a href="#s-11-8">Section 11.8</a>): PydanticAI's DeepSeek, Moonshot and Z.ai provider classes behind one adapter interface, the per-provider profiles for thinking control, reasoning pass-back and tool choice, providers.yaml and roles.yaml loading, tool-then-prompted structured output, fallback chains, explicit max_completion_tokens, the price table with peak and off-peak rates and usage-to-cost conversion, the no-price-no-run rule, and <code>qfr llm probe</code> scheduled at setup, daily and at job start.</label></li>
<li><input type="checkbox" id="t-P4-3" data-task="P4.3"><label for="t-P4-3"><b>P4.3</b> Implement the tool layer with role allow-lists, call logging and trace-step emission, and the tools from <a href="#s-11-3">Section 11.3</a>.</label></li>
<li><input type="checkbox" id="t-P4-4" data-task="P4.4"><label for="t-P4-4"><b>P4.4</b> Implement feedback sync into report_cache and report_links, with a per-program cursor.</label></li>
<li><input type="checkbox" id="t-P4-5" data-task="P4.5"><label for="t-P4-5"><b>P4.5</b> Implement the PydanticAI agents: supervisor, hypothesis researcher, factor engineer, critic, report analyst and interpretation reviewer, with versioned prompt files, per-role provider and model configuration, the cross-provider critic rule, and full request and response persistence in agent_runs.</label></li>
<li><input type="checkbox" id="t-P4-6" data-task="P4.6"><label for="t-P4-6"><b>P4.6</b> Generate the DSL reference card for prompts automatically from the operator registry, versioned and recorded in the trace.</label></li>
<li><input type="checkbox" id="t-P4-7" data-task="P4.7"><label for="t-P4-7"><b>P4.7</b> Implement the packager and the publishing path with full provenance and the trace completeness check (<a href="#s-14-5">Section 14.5</a>).</label></li>
<li><input type="checkbox" id="t-P4-8" data-task="P4.8"><label for="t-P4-8"><b>P4.8</b> Implement the generation state machine: persistence, resumability, retries, parallel tasks, plan validation with a deterministic fallback, and a trace step per transition.</label></li>
<li><input type="checkbox" id="t-P4-9" data-task="P4.9"><label for="t-P4-9"><b>P4.9</b> Implement the budget ledger in CNY with usage limits on every agent run, generation, daily and job caps, and the hard stop.</label></li>
<li><input type="checkbox" id="t-P4-10" data-task="P4.10"><label for="t-P4-10"><b>P4.10</b> Implement research jobs: brief validation and the owner-only scan, seed publication, deterministic charter derivation, the job state machine, the job monitor that checks deliverable criteria against released reports, deliverable and iteration-history assembly from the trace, and the research control API (<a href="#s-16-7">Section 16.7</a>).</label></li>
<li><input type="checkbox" id="t-P4-11" data-task="P4.11"><label for="t-P4-11"><b>P4.11</b> Add the MCP job, deliverable and trace tools: qfr.job.submit, list, get, events, wait, steer, pause, resume, cancel; qfr.deliverable.list and get composed with owner-grade evidence; qfr.trace.get; qfr.lineage.get; qfr.ops.costs; the resources and the qfr.brief and qfr.report_deliverable prompts.</label></li>
<li><input type="checkbox" id="t-P4-12" data-task="P4.12"><label for="t-P4-12"><b>P4.12</b> Build scripted LLM scenarios with FunctionModel and a scripted MCP client for offline end-to-end tests, and disable real model requests in the test suite.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>Offline end to end: a brief submitted through MCP produces a job, a generation with hypotheses, candidates, reviews and at most 12 publications; reports sync back; interpretations are written; a deliverable at tier w1_pass with an iteration history and owner-grade evidence is fetched through qfr.deliverable.get.</li>
<li>BND-02, BND-05, MCP-01, MCP-02, MCP-03, TRC-01, TRC-02 and LOG-03 pass. No generation or job exceeds its cost cap in tests.</li>
<li>Manual, owner-authorized: one real generation on the Mac Studio with each of the three providers as primary; costs recorded; <code>qfr llm probe</code> green for every configured model.</li>
</ul></div>
</div>

<!-- ---------------- Phase 5 -->
<div class="phase" id="ph-5">
<div class="phase-head"><h3>Phase 5 · Evolutionary engine</h3><span class="count">8 tasks</span></div>
<p class="goal"><strong>Goal.</strong> A diverse population that improves across generations under explicit budgets, with every variation step traced.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P5-1" data-task="P5.1"><label for="t-P5-1"><b>P5.1</b> Implement islands, population members, initialization from pools and seeds, the empty start, the MAP-Elites archive and lineage edges.</label></li>
<li><input type="checkbox" id="t-P5-2" data-task="P5.2"><label for="t-P5-2"><b>P5.2</b> Implement official and provisional fitness exactly as specified in <a href="#s-12-2">Section 12.2</a>, including the empty-library rule.</label></li>
<li><input type="checkbox" id="t-P5-3" data-task="P5.3"><label for="t-P5-3"><b>P5.3</b> Implement parent selection, deterministic syntactic mutation and subtree crossover, each emitting a trace step with the rule, seed and AST diff.</label></li>
<li><input type="checkbox" id="t-P5-4" data-task="P5.4"><label for="t-P5-4"><b>P5.4</b> Implement LLM-guided mutation and crossover prompts with flag-targeted instructions, the mode bias, plus the context assembler.</label></li>
<li><input type="checkbox" id="t-P5-5" data-task="P5.5"><label for="t-P5-5"><b>P5.5</b> Implement the publication pre-screen and selection with per-island fairness, each decision traced with its values.</label></li>
<li><input type="checkbox" id="t-P5-6" data-task="P5.6"><label for="t-P5-6"><b>P5.6</b> Implement the Thompson-sampling slot allocator, stagnation rules, migration and diversity guardrails.</label></li>
<li><input type="checkbox" id="t-P5-7" data-task="P5.7"><label for="t-P5-7"><b>P5.7</b> Extend the iteration history to DAG lineages (crossover) and discarded siblings, and implement qfr.trace.export.</label></li>
<li><input type="checkbox" id="t-P5-8" data-task="P5.8"><label for="t-P5-8"><b>P5.8</b> Build the benchmark harness for BM-PLANTED and BM-NULL at W1 level, driven through the MCP front door.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>On the planted world with the scripted LLM, the best island fitness improves over 10 generations, and a factor with rank correlation of 0.7 or more to A1 or A2 passes W1.</li>
<li>Archive coverage stays at or above 25% of cells. The null-world W1 pass rate is recorded and documented.</li>
<li>TRC-03 passes: the iteration history of a delivered version reconstructs every hop across five generations including a crossover.</li>
</ul></div>
</div>

<!-- ---------------- Phase 6 -->
<div class="phase" id="ph-6">
<div class="phase-head"><h3>Phase 6 · Validation, holdout, simulated trading, acceptance and pools</h3><span class="count">9 tasks</span></div>
<p class="goal"><strong>Goal.</strong> Trustworthy promotion: higher evidence tiers, strategies as deliverables, owner approvals and pool curation through MCP. Do not run long real-data campaigns before this phase is complete.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P6-1" data-task="P6.1"><label for="t-P6-1"><b>P6.1</b> Implement W2 runs, the Ladder release, and W2 quota and burn accounting.</label></li>
<li><input type="checkbox" id="t-P6-2" data-task="P6.2"><label for="t-P6-2"><b>P6.2</b> Implement the private W3 holdout check (one shot per version) and the advancement release.</label></li>
<li><input type="checkbox" id="t-P6-3" data-task="P6.3"><label for="t-P6-3"><b>P6.3</b> Implement nightly fingerprint clustering for N_eff and the DSR, PBO and HLZ gate computations.</label></li>
<li><input type="checkbox" id="t-P6-4" data-task="P6.4"><label for="t-P6-4"><b>P6.4</b> Implement the simulation engine with forward and replay modes: orders, fills, tradability, lots, costs, positions and NAV.</label></li>
<li><input type="checkbox" id="t-P6-5" data-task="P6.5"><label for="t-P6-5"><b>P6.5</b> Implement strategy artifacts v1: the StrategyDraft output and compose_strategy tasks on the research side, the strategy evaluation plugin and gates on the evaluation side, strategy deliverables with contribution tables, and the strategy modes in briefs.</label></li>
<li><input type="checkbox" id="t-P6-6" data-task="P6.6"><label for="t-P6-6"><b>P6.6</b> Implement acceptance cases, automated gates, decision and library releases, and the MCP tools qfr.acceptance.list_cases and qfr.acceptance.decide.</label></li>
<li><input type="checkbox" id="t-P6-7" data-task="P6.7"><label for="t-P6-7"><b>P6.7</b> Implement approval records and pool curation: qfr.approval.record with short-code matching, qfr.pool.add, qfr.pool.set_status, qfr.pool.annotate, qfr.job.close; evaluator library sync of approved tiers; the five-step workflow end to end.</label></li>
<li><input type="checkbox" id="t-P6-8" data-task="P6.8"><label for="t-P6-8"><b>P6.8</b> Implement library monitoring with decay alerts, the alerts table and qfr.ops.alerts.</label></li>
<li><input type="checkbox" id="t-P6-9" data-task="P6.9"><label for="t-P6-9"><b>P6.9</b> Run BM-PLANTED, BM-NULL, BM-DECAY and BM-STRATEGY end to end with replay incubation, and calibrate gates if needed.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>REL-05, REL-06, ACC-01 to ACC-03 and POOL-01 pass.</li>
<li>BM-NULL accepts zero factors. BM-PLANTED accepts at least one planted factor. BM-DECAY raises an alert. BM-STRATEGY delivers a strategy that passes its gates.</li>
<li>On the synthetic world, a scripted host agent completes all five workflow steps: brief, deliverable with iteration history and backtest results, approval recorded, factor pool entry and strategy pool entry written, library synced.</li>
</ul></div>
</div>

<!-- ---------------- Phase 7 -->
<div class="phase" id="ph-7">
<div class="phase-head"><h3>Phase 7 · Operator experience through the MCP front door</h3><span class="count">6 tasks</span></div>
<p class="goal"><strong>Goal.</strong> The owner can run, inspect and operate QFR entirely through the host agent, with exports they can open on the Mac.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P7-1" data-task="P7.1"><label for="t-P7-1"><b>P7.1</b> Implement deliverable export bundles (deliverable.json, iteration_history.md, trace.json, manifests, series Parquet and CSV, MANIFEST.sha256) under exports/, and qfr.deliverable.export.</label></li>
<li><input type="checkbox" id="t-P7-2" data-task="P7.2"><label for="t-P7-2"><b>P7.2</b> Complete the owner-grade evidence views: qfr.evidence.get with every window, gate values and simulation state; qfr.config.get owner_only; visibility labels and the holdout-hygiene warning in every evidence response.</label></li>
<li><input type="checkbox" id="t-P7-3" data-task="P7.3"><label for="t-P7-3"><b>P7.3</b> Implement the operations tools: qfr.status with queues, burn meters, quotas, data freshness and disk; qfr.ops.pause_research and resume_research; alert acknowledgement; cost summaries by job and provider.</label></li>
<li><input type="checkbox" id="t-P7-4" data-task="P7.4"><label for="t-P7-4"><b>P7.4</b> Harden log reading at scale: date-ranged search over compressed files, qfr.logs.export, the nightly compression and retention job with LOG-04, and the disk guard.</label></li>
<li><input type="checkbox" id="t-P7-5" data-task="P7.5"><label for="t-P7-5"><b>P7.5</b> Write docs/HOST_AGENT_GUIDE.md and the qfr.approval and qfr.investigate prompts; expose the guide as an MCP resource; add <code>just doctor</code> and <code>just restore-drill</code>.</label></li>
<li><input type="checkbox" id="t-P7-6" data-task="P7.6"><label for="t-P7-6"><b>P7.6</b> Rehearse the five-step workflow on the Mac Studio with a real host agent (Claude Code or Codex) on the synthetic world, following the guide; record the transcript, the audit rows and the exports as the runbook example.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>SC8: the rehearsal completes all five steps with a real host agent; every MCP call appears in mcp_calls and the logs; exports validate against their schemas.</li>
<li>SC9 and SC10: the trace export of the delivered version reconstructs every hop, and qfr.logs.correlate on the job id returns the whole story across services.</li>
<li>DEP-01 passes on the Mac Studio, and the restore drill passes.</li>
</ul></div>
</div>

<!-- ---------------- Phase 8 -->
<div class="phase" id="ph-8">
<div class="phase-head"><h3>Phase 8 · Hardening and extensions</h3><span class="count">7 tasks</span></div>
<p class="goal"><strong>Goal.</strong> Production hardening and the remaining artifact kinds, without changing the boundaries.</p>
<ul class="tasks">
<li><input type="checkbox" id="t-P8-1" data-task="P8.1"><label for="t-P8-1"><b>P8.1</b> Add Python factor artifacts executed in a hardened container: no network, read-only filesystem, CPU, memory and time limits, an AST import allow-list, and bans on date and identifier access; prefix invariance mandatory. Document that gVisor is unavailable on Docker Desktop for Mac and what that means.</label></li>
<li><input type="checkbox" id="t-P8-2" data-task="P8.2"><label for="t-P8-2"><b>P8.2</b> Extend strategy artifacts (long-short, industry neutrality once an industry dataset exists, position caps) and add research_note artifacts with output-quality checks.</label></li>
<li><input type="checkbox" id="t-P8-3" data-task="P8.3"><label for="t-P8-3"><b>P8.3</b> Add the optional Thresholdout mode for W2.</label></li>
<li><input type="checkbox" id="t-P8-4" data-task="P8.4"><label for="t-P8-4"><b>P8.4</b> Add epoch rollover tooling with a synthetic dry run and the qfr.ops.rollover_epoch tool.</label></li>
<li><input type="checkbox" id="t-P8-5" data-task="P8.5"><label for="t-P8-5"><b>P8.5</b> Optionally split Postgres into separate research and evaluation instances on separate networks, hash-chain the audit logs and automate backup verification.</label></li>
<li><input type="checkbox" id="t-P8-6" data-task="P8.6"><label for="t-P8-6"><b>P8.6</b> Add an industry-classification adapter for neutralization and a US-equities data adapter interface.</label></li>
<li><input type="checkbox" id="t-P8-7" data-task="P8.7"><label for="t-P8-7"><b>P8.7</b> Add CUSUM decay monitoring and the owner override for acceptance with a written rationale, a 24-hour cooling period and a second confirmation.</label></li>
</ul>
<div class="accept"><b>Acceptance checks</b><ul>
<li>Sandbox escape tests (network, filesystem, fork bomb, timeout) fail safely, and EVL-03 passes for Python factors.</li>
<li>A rollover dry run preserves every record link and every trace link.</li>
<li>All invariant tests still pass unchanged.</li>
</ul></div>
</div>

<h3 id="s-19-1"><span class="sn">19.1</span>Milestones</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Milestone</th><th>After phase</th><th>Demonstration</th></tr></thead>
<tbody>
<tr><td>M1 Measurable factors</td><td>3</td><td>Import a raw factor pool through MCP and watch coarsened reports get released as each evaluation finishes while the owner reads full-precision evidence</td></tr>
<tr><td>M2 Owner workflow</td><td>4</td><td>A brief through MCP yields a deliverable with an iteration history and backtest results, with a scripted LLM and with real providers</td></tr>
<tr><td>M3 Evolving system</td><td>5</td><td>Multi-generation improvement on the synthetic world, every hop traced, plus a smoke run on CN data</td></tr>
<tr><td>M4 Trustworthy promotion and pools</td><td>6</td><td>Full gates, incubation, strategies, owner approval and pool entries through MCP</td></tr>
<tr><td>M5 Operable through the host agent</td><td>7</td><td>The five-step workflow rehearsed on the Mac Studio with a real host agent, exports and logs readable</td></tr>
<tr><td>M6 Hardened platform</td><td>8</td><td>Sandbox, richer strategies, epoch rollover, overrides</td></tr>
</tbody>
</table>
</div>
<p>Sizing guidance: Phases 0 to 3 are the critical path and produce a useful system on their own (M1). Phase 4 is the owner's first real experience of QFR (M2) and should be shown to the owner as soon as it passes. Phase 5 adds the evolutionary depth. Phase 6 is what makes any promoted factor trustworthy and what fills the pools.</p>
</section>
<!-- ===================================================== CHAPTER 20 -->
<section class="chapter" id="ch-20">
<div class="chapter-kicker"><span class="n">20</span>Chapter 20</div>
<h2>Defaults<a class="anchor" href="#ch-20">#</a></h2>
<p>This table is the single source of truth for <code>configs/</code>. Every value is tunable by the owner through a new config version, and nothing may be hard-coded. Values marked <em>evaluator</em> change only by activating a new protocol, policy or quota version through MCP.</p>
<div class="table-wrap compact">
<table>
<thead><tr><th>Area</th><th>Parameter</th><th>Default</th><th>Changed by</th></tr></thead>
<tbody>
<tr><td>Protocol</td><td>Universe</td><td>CSI 300, point-in-time</td><td>Evaluator config</td></tr>
<tr><td>Protocol</td><td>Eligibility</td><td>Listed at least 60 days, not suspended, at least 30 names per date</td><td>Evaluator config</td></tr>
<tr><td>Protocol</td><td>Label</td><td>Close t+1 to close t+1+h. Horizons 1, 5, 10, 20. Primary horizon 1</td><td>Evaluator config</td></tr>
<tr><td>Protocol</td><td>Preprocessing</td><td>Winsorize 1% and 99%, then z-score. Size-neutral diagnostic</td><td>Evaluator config</td></tr>
<tr><td>Protocol</td><td>Quantiles, long-short cost</td><td>5 quantiles. 10 bps per side</td><td>Evaluator config</td></tr>
<tr><td>Protocol</td><td>Reference strategy</td><td>Top 50, dropout 5, daily, buy cost 5 bps, sell cost 15 bps. Strategies may set top_k 20..100 and dropout 1..20</td><td>Evaluator config</td></tr>
<tr><td>Protocol</td><td>Fingerprint</td><td>40 dates from W0, fixed seed</td><td>Evaluator config</td></tr>
<tr><td>Windows</td><td>Epoch 1</td><td>W0 2010-01-04 to 2019-12-31. W1 2020-02-04 to 2022-12-30. W2 2023-02-01 to 2024-06-28. W3 2024-08-01 to the last full month before the epoch. Embargo 20 trading days</td><td>Evaluator config</td></tr>
<tr><td>DSL</td><td>Complexity caps</td><td>30 nodes, depth 7, 4 fields, 3 constants, 250-day path lookback, 2 levels of Corr or Cov nesting</td><td>Evaluator config (research may be stricter)</td></tr>
<tr><td>DSL</td><td>Allowed windows</td><td>1, 2, 3, 5, 10, 20, 40, 60, 120, 250</td><td>Evaluator config</td></tr>
<tr><td>Screening</td><td>Thresholds</td><td>Coverage at least 0.80. Prefix probe on 5 dates at 1e-9 tolerance. 120 s CPU. 4 GB memory. Degenerate above 10% of dates</td><td>Evaluator config</td></tr>
<tr><td>Dedup</td><td>Behavioral threshold</td><td>Similarity at least 0.95</td><td>Evaluator config</td></tr>
<tr><td>Gates</td><td>W1 factor</td><td>Sign +1. RankIC at least 0.02. IR at least 0.12. NW t at least 2.5. Library correlation at most 0.70 (vacuous when empty). Turnover at most 0.60</td><td>Evaluator config</td></tr>
<tr><td>Gates</td><td>W1 strategy</td><td>Composite RankIC at least 0.02 and NW t at least 2.5. Net Sharpe at least 0.8. IR at least 0.5. Max drawdown at most 25%. Correlation with approved strategies at most 0.80</td><td>Evaluator config</td></tr>
<tr><td>Gates</td><td>W2</td><td>Factor: RankIC at least 0.015, IR at least 0.08, LS net Sharpe at least 0.5. Strategy: net Sharpe at least 0.5, IR at least 0.3</td><td>Evaluator config</td></tr>
<tr><td>Gates</td><td>Holdout</td><td>Factor: RankIC at least 0.01, LS net Sharpe at least 0.3, reference IR at least 0.3. Strategy: net Sharpe at least 0.3, IR at least 0.3</td><td>Evaluator config</td></tr>
<tr><td>Gates</td><td>Acceptance</td><td>DSR at least 0.90 with N_eff (clusters at 0.7). PBO at most 0.30 with S = 16. HLZ t at least 3.0. Incubation at least 60 days. Consistency z at least −1.645. Forward max drawdown at most 15%. Library correlation at most 0.60</td><td>Evaluator config</td></tr>
<tr><td>Release</td><td>Timing</td><td>Every report is released as soon as the evaluator records it. The release engine looks for new reports every second</td><td>Evaluator config</td></tr>
<tr><td>Release</td><td>Rounding</td><td>RankIC 0.005. IR 0.02. Sharpe 0.25. Shares and correlations 0.05. t buckets below 1, 1 to 2, 2 to 3, above 3. Ladder η 0.005</td><td>Evaluator config</td></tr>
<tr><td>Quotas</td><td>Per family, per program, global</td><td>3 W1 per 24 h and 1 W2 per 7 days per family. 60 W1 per day and 10 W2 per week per program. 200 W1 per day, 400 W2 per epoch, 100 W3 per epoch, 40 simulation slots. Deferral expiry 7 days</td><td>Evaluator config</td></tr>
<tr><td>Burn</td><td>W1 meter</td><td>Amber at 3,000 trials. Red at 6,000</td><td>Evaluator config</td></tr>
<tr><td>Simulation</td><td>Incubation</td><td>60 trading days. 20-day checkpoints. Capital 100,000,000 CNY. 100-share lots. Staleness alert after 2 days</td><td>Evaluator config</td></tr>
<tr><td>Monitoring</td><td>Decay alarm</td><td>Rolling 60-day RankIC mean below 0 for 20 consecutive days</td><td>Evaluator config</td></tr>
<tr><td>Research</td><td>Cadence</td><td>Next generation when the previous generation's feedback is complete, after at most 6 hours; the full 6 hours after a failed generation</td><td>Charter</td></tr>
<tr><td>Research</td><td>Throughput</td><td>12 publications per generation. 36 candidate slots at most. Concurrency 4. At most 2 review rounds. At most 2 compose_strategy tasks per generation</td><td>Charter</td></tr>
<tr><td>Research</td><td>Budget</td><td>Currency CNY. 20 per generation. 200 per day. 500 per job. Engineer runs limited to 12 requests and 20 tool calls</td><td>Charter and brief</td></tr>
<tr><td>Research</td><td>Context and temperature</td><td>12,000 tokens per prompt. Temperature 0.7 for explore and hypothesis tasks, 0.2 for supervisor, engineer, critic and analyst</td><td>roles.yaml</td></tr>
<tr><td>Providers</td><td>Role mapping</td><td>Supervisor DeepSeek strong (thinking, high effort); hypothesis Kimi strong; engineer GLM fast; critic DeepSeek strong and never the engineer's provider; analyst Kimi strong; interpretation reviewer GLM strong. Fallback chains and example ids as in <a href="#s-11-8">Section 11.8</a>, verified by the probe</td><td>roles.yaml</td></tr>
<tr><td>Providers</td><td>Requests</td><td>Concurrency 4. Timeout 120 s for fast roles, 600 s for thinking roles. 3 retries with backoff 2, 8, 30 s, then fallback. max_completion_tokens 4,096 for drafts and reviews, 16,384 for plans and interpretations. Structured output: tool calling with auto choice, prompted JSON after 2 failures. Prices required for every configured model. Probe at setup, daily and at job start</td><td>providers.yaml</td></tr>
<tr><td>Evolution</td><td>Population</td><td>6 islands, 60 members each, archive of 4 by 4 by 4 cells</td><td>Charter</td></tr>
<tr><td>Evolution</td><td>Selection</td><td>Exploit probability 0.7, tournament size 3 among the top 10</td><td>Charter</td></tr>
<tr><td>Evolution</td><td>Operator mix</td><td>Explore 25%, LLM mutation 35%, crossover 15%, syntactic 20%, repair 5%. Improve modes: explore 15%, LLM mutation 45%</td><td>Charter</td></tr>
<tr><td>Evolution</td><td>Pre-screen</td><td>W0 coverage at least 0.85. RankIC at least 0.015. IR at least 0.10. Similarity at most 0.90. Originality at least 0.2. Strategies: W0 net Sharpe at least 0.8, at most 8 components</td><td>Charter</td></tr>
<tr><td>Evolution</td><td>Bandit and guardrails</td><td>Forgetting 0.95. Floor 1 slot. Cap 40%. Stagnation after 8 generations. Migration every 5 generations. Coverage below 25% or top-20 similarity above 0.6 raises exploration to 40%</td><td>Charter</td></tr>
<tr><td>Jobs</td><td>Deliverable</td><td>Tier w1_pass. Minimum count 1. Maximum candidates 3. Maximum 10 generations. Maximum 14 wall-clock days</td><td>Brief</td></tr>
<tr><td>Pools</td><td>Statuses and tiers</td><td>seed, approved (w1_pass, w2_pass, advanced, incubated), retired. Import formats JSON, YAML, CSV</td><td>Fixed vocabulary</td></tr>
<tr><td>MCP</td><td>Transport and limits</td><td>Streamable HTTP on 127.0.0.1:8765, path /mcp. Bearer token. Body 1 MB. Long-poll 600 s. Lists and logs 200 default, 2,000 maximum per call. One approval-gated write at a time</td><td>mcp.yaml</td></tr>
<tr><td>MCP</td><td>Approvals</td><td>Confirmation must contain every short code in scope. Short code format J-nnnn F-k / S-k</td><td>mcp.yaml</td></tr>
<tr><td>Logging</td><td>Levels and storage</td><td>INFO default. JSON lines per service per day on qfr_logs. Roll at 512 MB. Gzip after 7 days. Delete after 180 days. Disk warning at 20 GB</td><td>logging.yaml</td></tr>
<tr><td>Trace</td><td>Retention</td><td>Full prompts and responses retained indefinitely. Owner-only evidence never stored in research_db</td><td>Fixed</td></tr>
<tr><td>Deployment</td><td>Mac Studio</td><td>Docker Desktop with at least 8 CPUs, 24 GB memory, 200 GB disk. eval-worker 2 replicas at 4 CPU and 6 GB. TZ Asia/Shanghai. Ingest 18:30. Nightly jobs 02:30. Backups 30 daily and 12 monthly</td><td>compose and .env</td></tr>
</tbody>
</table>
</div>
</section>

<!-- ===================================================== CHAPTER 21 -->
<section class="chapter" id="ch-21">
<div class="chapter-kicker"><span class="n">21</span>Chapter 21</div>
<h2>Coding-agent kit<a class="anchor" href="#ch-21">#</a></h2>

<h3 id="s-21-1"><span class="sn">21.1</span>AGENTS.md</h3>
<p>Copy this block verbatim into the repository root.</p>
<pre><code># AGENTS.md: rules for every coding session

Project: QFR, the owner-driven Multi-Agent Quantitative Factor Research and Evolution System.
Source of truth: docs/PLAN.md. Decision log: docs/decisions.md. Build only what PLAN.md says.

## Non-negotiable invariants (each one has tests; never weaken them)
1. Research code never invokes, configures, prioritizes or cancels evaluation, and never touches simulated accounts or pools. No such tool, endpoint or credential may exist on the research side.
2. Published artifact versions are immutable. Any change creates a new version. Pool changes are append-only events.
3. The evaluator pulls artifacts and pool changes on its own schedule. There is no push or trigger from research or from the front door.
4. Research reads feedback only through the GET-only Feedback API, which serves released reports only.
5. Every official record and released report references the artifact version id, content hash, protocol version, data snapshot id and evaluator code version.
6. W3 holdout numbers never reach research. Only decisions and reason categories leave the evaluation zone toward research. The owner reads them through the eval admin API only.
7. Every evaluated version is written to the trial ledger, including failures.
8. Official measurement has no LLM, no network and no wall-clock dependence. Results are reproducible bit for bit.
9. Research processes read only the research-zone snapshot (dates on or before the cutoff) and only their own logs.
10. Every write is attributed to a principal and logged in an append-only event table, and every MCP call is audited.
11. Nothing enters a pool and no acceptance case closes as accepted without an approval record created from the owner's verbatim confirmation through MCP. No code path promotes automatically.
12. Released diagnostics are enum codes only. Never release free text produced by executing artifact code.
13. Every published version has a complete, append-only development trace. The packager refuses to publish without it. Agent runs store the full request and response.
14. The MCP front door exposes owner-grade control only: briefs, reads, approvals, pool curation, operations and logs. It never runs research tools, publishes, writes official records, alters runs or holds LLM keys.

## Engineering rules
- Python 3.12 in a uv workspace with packages qfr_core, qfr_registry, qfr_research, qfr_eval and qfr_mcp. import-linter contracts must pass; qfr_mcp imports only qfr_core.
- Every tunable lives in configs/*.yaml with the defaults from PLAN Section 20. No magic numbers.
- There are no default factors, default strategies, demo seeds or reference samples in code or configuration. A fresh deployment is empty until the owner imports a raw factor pool.
- Research LLMs are the Kimi, GLM and DeepSeek online APIs through OpenAI-compatible chat completions, reached through PydanticAI's provider classes and configured per role in configs/research. Never hard-code a model id, endpoint, price or thinking setting. Never force tool_choice. Never add another provider or a local model.
- Every cross-boundary payload is a Pydantic v2 model, validated before it is persisted.
- Timing convention: factor at close t, execution at close t+1, label from close t+1 to close t+1+h.
- Log everything through the shared structlog setup with the mandatory fields and correlation ids. A log line about an entity carries that entity's id. Never log a secret; the redaction processor is mandatory on every sink.
- Every step that changes what happens to a candidate is a trace step written by deterministic code, never by an agent.
- Write tests together with each feature. Tests never call real providers: disable model requests and use FunctionModel or TestModel. Tests never call a real MCP client; use the scripted client.
- Use deterministic seeds everywhere. Hashed outputs use canonical JSON with sorted keys and no unordered iteration.
- Schema changes go through Alembic only. Insert-only tables are protected by triggers.
- Official-record schemas live in qfr_eval and must never be imported by research code or qfr_mcp.
- Images are built for linux/arm64 first; a dependency without an arm64 wheel is not an option.
- When the plan is ambiguous, choose the option that better protects measurement integrity and traceability, record it in docs/decisions.md and continue.
- A task is done when code, tests, logs and docs are updated and the check and test targets are green.</code></pre>

<h3 id="s-21-2"><span class="sn">21.2</span>Phase kickoff prompt</h3>
<p>Use this template to start each phase. Replace the placeholders.</p>
<pre><code>You are implementing Phase &lt;N&gt; of docs/PLAN.md for the QFR system.
1. Read AGENTS.md, then PLAN Sections &lt;list from the table below&gt;, then the Phase &lt;N&gt; task list in Section 19.
2. Implement tasks &lt;Pn.1 ... Pn.k&gt; in order. For each task: implement it, add tests, add the log events and trace steps the plan names, run the check and test targets, and fix until green.
3. Do not modify invariants or weaken existing tests. Do not add default factors, strategies or providers. Record every ambiguity and your resolution in docs/decisions.md.
4. At the end, run every Phase &lt;N&gt; acceptance check and report each as PASS or FAIL with evidence (test names and command output summaries). Checks marked "on the Mac Studio" are run there by the owner; prepare the exact commands.
5. List any follow-ups that belong to later phases instead of implementing them now.</code></pre>
<div class="table-wrap compact">
<table>
<thead><tr><th>Phase</th><th>Sections to read</th></tr></thead>
<tbody>
<tr><td>0</td><td>3, 4, 5, 15, 17.2, 20, 21</td></tr>
<tr><td>1</td><td>6, 7, 8.5 to 8.7, 18</td></tr>
<tr><td>2</td><td>7.6 to 7.9, 13.6, 16.1, 16.5</td></tr>
<tr><td>3</td><td>8, 9, 16.3, 16.6, 16.8</td></tr>
<tr><td>4</td><td>11, 13, 14, 16.2, 16.7</td></tr>
<tr><td>5</td><td>12, 14</td></tr>
<tr><td>6</td><td>7.8, 8.7, 8.8, 9, 10, 13.5</td></tr>
<tr><td>7</td><td>13, 14.5, 15.5, 17.3 to 17.5, 21.3</td></tr>
<tr><td>8</td><td>7.6, 8.10, 9.5, 10.6, 17.1</td></tr>
</tbody>
</table>
</div>

<h3 id="s-21-3"><span class="sn">21.3</span>Host-agent guide (summary of docs/HOST_AGENT_GUIDE.md)</h3>
<p>The guide is written for the agent that drives QFR on the owner's behalf. It is also served as the MCP resource <code>qfr://docs/host-agent-guide</code> so any host agent can read it before its first call.</p>
<pre><code># How to drive QFR as a host agent

You are not a QFR research agent. You translate the owner's intent into briefs, follow jobs,
explain deliverables, and record the owner's decisions. QFR does the research and the measurement.

Before the first brief
- Call qfr.status. If setup is incomplete, walk the owner through qfr.setup.status and qfr.pool.import.
- Read qfr://cards/protocol and qfr://cards/policy. Read both pools. Tell the owner what exists.

Writing a brief (prompt qfr.brief)
- Pick the mode: new_factors, improve_factors, new_strategy, improve_strategy or review_and_iterate.
- Put the owner's words in objective. Put document summaries in seeds.notes.
- Extract candidate factors from documents as DSL expressions; validate each with qfr.dsl.validate; fix or drop invalid ones and tell the owner.
- Reference pool entries and versions by id. Never paste owner-only numbers (W3, gate values, full-precision records) into a brief or a steering note.
- Choose the deliverable tier with the owner: w1_pass is fast and weak evidence; incubated is slow and strong. Say the timeline out loud.
- Set a budget the owner agreed to.

Following a job
- Use qfr.job.wait, then qfr.job.get. Do not poll in a tight loop. Report state changes and costs.
- If the owner wants to change direction, use qfr.job.steer; to stop spending, qfr.job.pause or qfr.job.cancel.

Reporting a deliverable (prompt qfr.report_deliverable)
- State the tier reached first, then the artifact, then the backtest results from owner_evidence with their windows, then the caveats verbatim, then the iteration history in hop order.
- Quote the short codes. Do not round, omit or reinterpret evaluator numbers. Research-side W0 numbers are in-sample; say so.

Recording decisions (prompt qfr.approval)
- Ask the owner for an explicit decision that includes the short codes, for example "APPROVE J-0042 F-1 F-2".
- Call qfr.approval.record with the owner's words verbatim and your one-paragraph rationale. Then qfr.pool.add for each approved item, or qfr.job.close for a rejection.
- Never record an approval the owner did not state. Never approve on your own judgement.

Investigating (prompt qfr.investigate)
- "How was this factor developed": qfr.trace.get, then qfr.lineage.get.
- "What happened to job X": qfr.job.events, then qfr.logs.correlate(job_id).
- "Why did version Y fail": qfr.report.list, then qfr.evidence.get, then qfr.logs.correlate(version_id).
- "Is the system healthy": qfr.status, qfr.ops.alerts, qfr.logs.search(level=ERROR, last 24 hours).</code></pre>

<h3 id="s-21-4"><span class="sn">21.4</span>Global definition of done</h3>
<ul>
  <li>Every phase acceptance check passes in CI, and all invariant tests are green. Checks marked for the Mac Studio have passed there and their <code>just doctor</code> report is in <code>exports/doctor/</code>.</li>
  <li><code>docs/decisions.md</code> lists every deviation from the plan, with its reason.</li>
  <li>No TODO comments remain in boundary-related code (tool registry, MCP catalog, APIs, grants, release engine, packager completeness check).</li>
  <li>At least one official record per phase that touches evaluation has been reproduced with <code>qfr eval reproduce</code>.</li>
  <li>For every phase from 4 on, one deliverable's trace export and iteration history have been read by a human and found to reconstruct the development path.</li>
  <li>No default factors, strategies, seeds or samples exist anywhere in the repository.</li>
</ul>
</section>

<!-- ===================================================== CHAPTER 22 -->
<section class="chapter" id="ch-22">
<div class="chapter-kicker"><span class="n">22</span>Chapter 22</div>
<h2>Risks and mitigations<a class="anchor" href="#ch-22">#</a></h2>
<div class="table-wrap compact">
<table>
<thead><tr><th>Risk</th><th>Likelihood</th><th>Impact</th><th>Mitigation</th></tr></thead>
<tbody>
<tr><td>Overfitting to W1 through the sheer volume of search</td><td>High</td><td>High</td><td>Quotas, coarsening, trial ledger, DSR with N_eff, W2 Ladder, private W3, incubation for the top tier, tiers stated on every deliverable</td></tr>
<tr><td>LLM memorization inflates historical results</td><td>High</td><td>High</td><td>DSL without identifiers or dates, prompt rules, critic checks for period narratives, forward incubation, caveats in every deliverable</td></tr>
<tr><td>The owner approves on weak evidence because it is fast</td><td>Medium</td><td>Medium</td><td>Tier stated first in every report; the pool records the tier; evidence keeps accumulating and decay alerts reach the owner; the host-agent guide explains the trade-off</td></tr>
<tr><td>Owner-only numbers leak into research through briefs</td><td>Medium</td><td>High</td><td>Ids instead of evidence objects, deterministic scan on briefs and steering notes, host-agent guide, audit of every call; residual risk recorded</td></tr>
<tr><td>The host agent misrepresents or over-approves</td><td>Medium</td><td>Medium</td><td>Verbatim confirmations with short codes, insert-only approvals, full audit readable back through MCP, deterministic deliverable summaries and caveats</td></tr>
<tr><td>The community data source breaks or contains errors</td><td>Medium</td><td>Medium</td><td>Manifest and checksum validation, pinned snapshots, ingest sanity checks, synthetic fallback, adapter interface for other sources</td></tr>
<tr><td>Provider outage, rate limits or API drift</td><td>Medium</td><td>Medium</td><td>Three providers with fallback chains, retries, one adapter interface with per-provider profiles, the probe, explicit max_completion_tokens, alerts on repeated fallbacks</td></tr>
<tr><td>A provider retires or renames a model mid-project (three such changes happened in the twelve months before this plan)</td><td>High</td><td>Low</td><td>Model ids are configuration only; the probe runs at setup, daily and at job start and alerts on a missing id; fallback chains keep jobs running; replacement is a config change plus a research-worker restart</td></tr>
<tr><td>Provider price changes make budgets wrong</td><td>Medium</td><td>Low</td><td>Prices are configuration checked at setup; no-price-no-run; costs logged per call and summarized per job</td></tr>
<tr><td>Mode collapse and low diversity</td><td>Medium</td><td>Medium</td><td>Islands, MAP-Elites archive, novelty in fitness, diversity guardrails, exploration floor, roles spread across providers</td></tr>
<tr><td>LLM cost overrun</td><td>Medium</td><td>Medium</td><td>Per-run usage limits, generation, daily and job caps, hard stop, fast tier for bulk work</td></tr>
<tr><td>Redundant factor zoo</td><td>Medium</td><td>Medium</td><td>Library-correlation gates against the pools, behavioral dedup, novelty gate at acceptance</td></tr>
<tr><td>Empty pools make early research directionless</td><td>Medium</td><td>Low</td><td>Intended. The first generation is pure exploration; the owner can import seeds at any time; briefs carry the owner's intent</td></tr>
<tr><td>Trace and log storage grows unnoticed</td><td>Low</td><td>Low</td><td>Sizing is small (under 10 GB per year of trace, under 1 GB per day of logs); rotation, compression, retention and a disk guard</td></tr>
<tr><td>Docker Desktop on macOS: sleep, slow bind mounts, resource starvation</td><td>Medium</td><td>Medium</td><td>Sleep disabled, named volumes for data and databases, explicit VM sizing and per-service limits, <code>just doctor</code>, staleness alerts</td></tr>
<tr><td>No sandbox isolation beyond Docker on macOS</td><td>Low</td><td>Medium</td><td>v1 executes no artifact code; Phase 8 Python factors use hardened containers with no network; documented as a residual risk</td></tr>
<tr><td>Simplified cost and tradability model misstates capacity</td><td>Medium</td><td>Medium</td><td>Conservative costs. Capacity is flagged out of scope in every acceptance case and deliverable caveat</td></tr>
<tr><td>Survivorship or point-in-time errors</td><td>Low to medium</td><td>High</td><td>Point-in-time index files, delisted names retained, tests with synthetic universe churn</td></tr>
<tr><td>Boundary erosion over time</td><td>Medium</td><td>High</td><td>Invariant tests in CI and in <code>just doctor</code>, import-linter, snapshot tests of the tool registry and MCP catalog</td></tr>
<tr><td>Coarsening hides genuine small improvements from research</td><td>Medium</td><td>Low</td><td>Intended. Fine-grained iteration happens on W0; the owner sees full precision</td></tr>
</tbody>
</table>
</div>
</section>

<!-- ===================================================== CHAPTER 23 -->
<section class="chapter" id="ch-23">
<div class="chapter-kicker"><span class="n">23</span>Chapter 23</div>
<h2>Glossary and references<a class="anchor" href="#ch-23">#</a></h2>

<h3 id="s-23-1"><span class="sn">23.1</span>Glossary</h3>
<div class="table-wrap compact">
<table>
<thead><tr><th>Term</th><th>Meaning</th></tr></thead>
<tbody>
<tr><td>Owner</td><td>The single human who steers QFR, approves results and curates the pools</td></tr>
<tr><td>Host agent</td><td>The owner's agent (Codex, Claude Code or any MCP client) that drives QFR through the MCP front door</td></tr>
<tr><td>MCP front door</td><td>The <code>qfr-mcp</code> server: QFR's only human-facing control surface</td></tr>
<tr><td>Research brief</td><td>The structured description of what the owner wants, derived by the host agent and submitted as a job</td></tr>
<tr><td>Research job</td><td>One brief, one program, one or more deliverables</td></tr>
<tr><td>Deliverable</td><td>An artifact with its iteration history, released reports, owner-grade backtest results and caveats, handed to the host agent when a job's criteria are met</td></tr>
<tr><td>Evidence tier</td><td>How far a version has progressed: w1_pass, w2_pass, advanced (holdout), incubated (forward simulation and accepted case)</td></tr>
<tr><td>Iteration history</td><td>The owner-facing rendering of how a version developed from its roots, generated from the trace</td></tr>
<tr><td>Development trace</td><td>The append-only, step-level record of everything that happened to a candidate, written by deterministic code</td></tr>
<tr><td>Approval record</td><td>The owner's verbatim confirmation and scope, required for every pool write and acceptance decision</td></tr>
<tr><td>Factor pool, strategy pool</td><td>The owner's long-lived, curated collections of approved versions, append-only, starting empty</td></tr>
<tr><td>Seed</td><td>A pool entry imported at setup from the raw factor pool, or a brief expression published at job start</td></tr>
<tr><td>Library</td><td>The evaluator's view of the pools, used for correlation and novelty checks</td></tr>
<tr><td>Owner-grade evidence</td><td>Full-precision official records and gate values, readable only through the front door</td></tr>
<tr><td>Provider</td><td>One of Kimi, GLM or DeepSeek, reached through an OpenAI-compatible endpoint</td></tr>
<tr><td>Artifact version</td><td>An immutable, content-hashed published unit (factor, strategy or research note)</td></tr>
<tr><td>Family</td><td>All versions descending from one artifact, sharing a family id</td></tr>
<tr><td>Trial</td><td>One artifact version evaluated on one window, counted in the trial ledger</td></tr>
<tr><td>Official record</td><td>The evaluator's immutable, full-precision result for one version and stage</td></tr>
<tr><td>Released report</td><td>The coarsened, policy-filtered view of official records that research may read</td></tr>
<tr><td>Protocol card, policy card</td><td>Public summaries of the evaluation protocol and the release policy</td></tr>
<tr><td>Burn meter</td><td>Per-window accounting of how much information has been spent through trials and releases</td></tr>
<tr><td>Island, archive cell</td><td>A themed sub-population; a MAP-Elites niche defined by horizon, turnover and field group</td></tr>
<tr><td>Incubation</td><td>Forward simulated trading after publication (W4)</td></tr>
<tr><td>RankIC and IR</td><td>Daily Spearman correlation between factor and forward return, and its mean divided by its standard deviation</td></tr>
<tr><td>DSR, PBO and CSCV, Ladder, Thresholdout</td><td>Deflated Sharpe Ratio; probability of backtest overfitting by combinatorially symmetric cross-validation; a leaderboard that releases a new best only on a margin improvement; a reusable-holdout mechanism</td></tr>
<tr><td>Point-in-time, embargo</td><td>Using only information as known on each date; a gap between windows so labels never straddle two windows</td></tr>
</tbody>
</table>
</div>

<h3 id="s-23-2"><span class="sn">23.2</span>References</h3>
<ul>
  <li>Model Context Protocol specification and SDKs. https://modelcontextprotocol.io — tools, resources, prompts, streamable HTTP transport.</li>
  <li>Pydantic AI documentation: agents, OpenAI-compatible providers, usage limits, testing with TestModel and FunctionModel. https://ai.pydantic.dev</li>
  <li>DeepSeek API documentation (OpenAI-compatible endpoint, models, pricing). https://api-docs.deepseek.com</li>
  <li>Moonshot AI (Kimi) API documentation. https://platform.moonshot.cn/docs</li>
  <li>Zhipu AI (GLM) open platform documentation. https://open.bigmodel.cn/dev/api</li>
  <li>Docker Desktop for Mac documentation: Apple silicon, resource settings, file sharing. https://docs.docker.com/desktop/setup/install/mac-install/</li>
  <li>structlog documentation. https://www.structlog.org</li>
  <li>Li et al. (2025). R&amp;D-Agent-Quant: A Multi-Agent Framework for Data-Centric Factors and Model Joint Optimization. NeurIPS 2025. https://arxiv.org/abs/2505.15155</li>
  <li>Tang et al. (2025). AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay. KDD 2025. https://arxiv.org/abs/2502.16789</li>
  <li>QuantaAlpha: An Evolutionary Framework for LLM-Driven Alpha Mining (2026). https://arxiv.org/abs/2602.07085</li>
  <li>AlphaAgentEvo: Evolution-Oriented Alpha Mining via Self-Evolving Agentic Reinforcement Learning. ICLR 2026.</li>
  <li>Novikov et al. (2025). AlphaEvolve, Google DeepMind white paper, and the open-source OpenEvolve implementation. https://github.com/algorithmicsuperintelligence/openevolve</li>
  <li>Dwork, Feldman, Hardt, Pitassi, Reingold and Roth (2015). The reusable holdout, Science; Generalization in adaptive data analysis and holdout reuse, NeurIPS. https://arxiv.org/abs/1506.02629</li>
  <li>Blum and Hardt (2015). The Ladder: A Reliable Leaderboard for Machine Learning Competitions. ICML. https://arxiv.org/abs/1502.04585</li>
  <li>Bailey and López de Prado (2014). The Deflated Sharpe Ratio. https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf</li>
  <li>Bailey, Borwein, López de Prado and Zhu (2017). The Probability of Backtest Overfitting. Journal of Computational Finance.</li>
  <li>Harvey, Liu and Zhu (2016). … and the Cross-Section of Expected Returns. Review of Financial Studies.</li>
  <li>López de Prado (2018). Advances in Financial Machine Learning: purged cross-validation and embargo.</li>
  <li>Newey and West (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. Econometrica.</li>
  <li>Glasserman and Lin (2023). Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis. https://arxiv.org/abs/2309.17322</li>
  <li>Lopez-Lira et al. (2025). The Memorization Problem: Can We Trust LLMs' Economic Forecasts? https://arxiv.org/abs/2504.14765</li>
  <li>Gao, Jiang and Yan (2025). Detecting Lookahead Bias in LLM Forecasts. https://arxiv.org/abs/2512.23847</li>
  <li>chenditc/investment_data (community A-share dataset in Qlib format). https://github.com/chenditc/investment_data</li>
  <li>Microsoft Qlib. https://github.com/microsoft/qlib</li>
  <li>import-linter. https://import-linter.readthedocs.io</li>
</ul>
</section>

</main>
</div>

<footer class="foot">
  <span>QFR Implementation Plan v2 · Generated 2026-10-30 · 24 chapters · 76 tasks · 5 figures · single-file HTML, works offline</span>
  <a href="#top">Back to top</a>
</footer>
<button class="to-top" id="to-top" type="button" title="Back to top" aria-label="Back to top"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg></button>

<script>
(function(){
  'use strict';
  var root=document.documentElement;
  var LS=function(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v);}catch(e){return null;}};
  /* theme */
  var themeBtn=document.getElementById('theme-btn'),themeLabel=document.getElementById('theme-label');
  var order=['auto','light','dark'];
  function applyTheme(t){root.setAttribute('data-theme',t);themeLabel.textContent=t.charAt(0).toUpperCase()+t.slice(1);}
  applyTheme(LS('qfr-plan-v2-theme')||'auto');
  themeBtn.addEventListener('click',function(){var cur=root.getAttribute('data-theme')||'auto';var next=order[(order.indexOf(cur)+1)%order.length];applyTheme(next);LS('qfr-plan-v2-theme',next);});
  /* reading progress + back to top */
  var bar=document.getElementById('read-bar'),toTop=document.getElementById('to-top');
  function onScroll(){var h=document.documentElement;var max=h.scrollHeight-h.clientHeight;var p=max>0?(h.scrollTop/max)*100:0;bar.style.width=p+'%';toTop.classList.toggle('show',h.scrollTop>600);}
  window.addEventListener('scroll',onScroll,{passive:true});onScroll();
  toTop.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});});
  /* TOC active highlighting */
  var tocLinks=Array.prototype.slice.call(document.querySelectorAll('#toc-list a'));
  var targets=tocLinks.map(function(a){return document.getElementById(a.getAttribute('href').slice(1));}).filter(Boolean);
  var byId={};tocLinks.forEach(function(a){byId[a.getAttribute('href').slice(1)]=a;});
  if('IntersectionObserver' in window){
    var current=null;
    var io=new IntersectionObserver(function(entries){
      entries.forEach(function(en){if(en.isIntersecting){current=en.target.id;}});
      if(current&&byId[current]){tocLinks.forEach(function(a){a.classList.remove('active');});byId[current].classList.add('active');
        var el=byId[current];var nav=el.closest('.toc');if(nav){var r=el.getBoundingClientRect(),nr=nav.getBoundingClientRect();if(r.top<nr.top||r.bottom>nr.bottom){el.scrollIntoView({block:'nearest'});}}}
    },{rootMargin:'-80px 0px -70% 0px',threshold:0});
    targets.forEach(function(t){io.observe(t);});
  }
  /* TOC filter */
  var filter=document.getElementById('toc-filter'),toc=document.querySelector('.toc'),empty=document.querySelector('.toc-empty');
  filter.addEventListener('input',function(){
    var q=filter.value.trim().toLowerCase();var any=false;
    toc.classList.toggle('filtering',!!q);
    document.querySelectorAll('#toc-list li').forEach(function(li){var hit=!q||li.textContent.toLowerCase().indexOf(q)>=0;li.classList.toggle('hide',!hit);if(hit)any=true;});
    empty.classList.toggle('show',!!q&&!any);
  });
  document.addEventListener('keydown',function(e){if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();filter.focus();filter.select();}});
  /* checklist persistence */
  var KEY='qfr-plan-v2-progress';
  var boxes=Array.prototype.slice.call(document.querySelectorAll('.tasks input[type=checkbox]'));
  var state={};try{state=JSON.parse(LS(KEY)||'{}')||{};}catch(e){state={};}
  function render(){var done=0;boxes.forEach(function(b){var on=!!state[b.dataset.task];b.checked=on;b.closest('li').classList.toggle('done',on);if(on)done++;});
    var pb=document.getElementById('progress-bar'),pn=document.getElementById('progress-num');
    if(pb){pb.style.width=(boxes.length?done/boxes.length*100:0)+'%';}if(pn){pn.textContent=done+'/'+boxes.length;}}
  boxes.forEach(function(b){b.addEventListener('change',function(){state[b.dataset.task]=b.checked;if(!b.checked)delete state[b.dataset.task];LS(KEY,JSON.stringify(state));render();});});
  var reset=document.getElementById('progress-reset');if(reset){reset.addEventListener('click',function(){if(confirm('Clear all ticked tasks in this browser?')){state={};LS(KEY,'{}');render();}});}
  render();
  /* print: open all details */
  window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){d.setAttribute('open','');});});
})();
</script>
</body>
</html>
