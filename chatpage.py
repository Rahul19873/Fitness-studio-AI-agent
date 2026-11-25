"""The customer chat page, stored as text so no separate HTML file is needed."""

CHAT_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Chat</title>
<style>
  :root {
    --bg:#f3f5f7; --card:#ffffff; --text:#1c2430; --muted:#667085; --line:#e4e7ec;
    --accent:#0f766e; --accent-text:#ffffff; --user:#0f766e; --user-text:#ffffff; --bot:#eef1f4;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0e1319; --card:#161d26; --text:#e6e9ee; --muted:#9aa4b2; --line:#2a3442;
            --accent:#2dd4bf; --accent-text:#06231f; --user:#14b8a6; --user-text:#04201c; --bot:#212b38; }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { font: 16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--text);
         display: flex; justify-content: center; }
  .app { width: 100%; max-width: 560px; height: 100%; display: flex; flex-direction: column; background: var(--card);
         padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); }
  header { padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 10px; }
  header h1 { font-size: 17px; margin: 0; flex: 1; }
  .pill { font-size: 12px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; }
  #log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
  .msg { max-width: 82%; padding: 9px 13px; border-radius: 16px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .bot { background: var(--bot); align-self: flex-start; border-bottom-left-radius: 4px; }
  .me { background: var(--user); color: var(--user-text); align-self: flex-end; border-bottom-right-radius: 4px; }
  .err { color: #b42318; font-size: 14px; align-self: center; text-align: center; }
  .typing { color: var(--muted); }
  form { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); }
  input { flex: 1; font: inherit; padding: 11px 14px; border: 1px solid var(--line); border-radius: 999px;
          background: var(--bg); color: var(--text); min-width: 0; }
  input:focus { outline: 2px solid var(--accent); outline-offset: 0; }
  button { font: inherit; font-weight: 600; border: 0; border-radius: 999px; padding: 0 20px;
           background: var(--accent); color: var(--accent-text); cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  .note { font-size: 12px; color: var(--muted); text-align: center; padding: 0 14px 10px; }
</style>
</head>
<body>
<div class="app">
  <header><h1 id="name">Chat</h1><span class="pill">AI assistant</span></header>
  <div id="log" aria-live="polite"></div>
  <form id="form" autocomplete="off">
    <input id="text" type="text" maxlength="600" placeholder="Type your message…" aria-label="Your message">
    <button id="send" type="submit">Send</button>
  </form>
  <div class="note">You’re chatting with an AI assistant. Chats are saved so the team can follow up.
    Please don’t share passwords or payment details.</div>
</div>
<script>
  const log = document.getElementById("log");
  const form = document.getElementById("form");
  const input = document.getElementById("text");
  const send = document.getElementById("send");
  // "/c/<business>" uses that business's API; the single-business edition uses "/api".
  const parts = location.pathname.split("/");
  const base = (parts[1] === "c" && parts[2]) ? "/api/c/" + encodeURIComponent(parts[2]) : "/api";
  // A new chat starts each time the page loads; nothing is stored in the browser.
  const sid = (self.crypto && crypto.randomUUID ? crypto.randomUUID()
              : Date.now().toString(36) + Math.random().toString(36).slice(2, 12)).replace(/[^a-zA-Z0-9-]/g, "");

  function add(cls, text) {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    d.textContent = text;            // textContent, never innerHTML: replies can't inject code
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  fetch(base + "/info").then(r => { if (!r.ok) throw new Error("unavailable"); return r.json(); }).then(i => {
    document.getElementById("name").textContent = i.name;
    document.title = i.name;
    add("bot", i.greeting);
  }).catch(() => { add("err", "This chat isn’t available right now. Please try again later."); form.style.display = "none"; });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    add("me", text);
    input.value = "";
    send.disabled = true;
    const typing = add("bot typing", "Typing…");
    try {
      const r = await fetch(base + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, message: text })
      });
      const data = await r.json().catch(() => ({}));
      typing.remove();
      if (r.ok) add("bot", data.reply);
      else add("err", typeof data.detail === "string" ? data.detail : "Something went wrong. Please try again.");
    } catch (err) {
      typing.remove();
      add("err", "No connection. Please check your internet and try again.");
    } finally {
      send.disabled = false;
      input.focus();
    }
  });
</script>
</body>
</html>
"""
