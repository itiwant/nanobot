---
name: browser
description: "Control a real browser via PinchTab MCP: navigate, click, fill forms, snapshot, extract text, take screenshots, generate PDFs, run JavaScript, manage cookies and tabs."
metadata: {"nanobot":{"emoji":"🌐","requires":{"bins":[]}}}
---

# Browser Skill (PinchTab)

Use these tools when the agent needs to browse the web, interact with pages, or extract content. All tools are provided by the PinchTab MCP server and are registered with the `mcp_pinchtab_` prefix.

## Setup

Ensure PinchTab is configured in `tools.mcpServers`. Once connected, nanobot auto-discovers and registers all browser tools.

---

## Tool Reference

### `mcp_pinchtab_navigate` — Go to a URL

Navigate the browser to any URL.

```
mcp_pinchtab_navigate(url="https://example.com")
```

- Returns the final URL and page title after navigation.
- Use before any extraction or interaction tools.

---

### `mcp_pinchtab_snapshot` — Accessibility snapshot (token-efficient)

Get a structured accessibility tree of the current page. Preferred over screenshot for locating elements.

```
mcp_pinchtab_snapshot()
```

- Returns element references (`ref` values like `e5`, `e12`) needed by `mcp_pinchtab_action`.
- Use this to find buttons, links, inputs, and other interactive elements.

---

### `mcp_pinchtab_action` — Perform a single interaction

Perform one user action on an element identified by its `ref` from a snapshot.

```
mcp_pinchtab_action(kind="click", ref="e5")
mcp_pinchtab_action(kind="fill", ref="e9", value="hello world")
mcp_pinchtab_action(kind="select", ref="e14", value="option-value")
mcp_pinchtab_action(kind="check", ref="e3")
mcp_pinchtab_action(kind="uncheck", ref="e3")
mcp_pinchtab_action(kind="hover", ref="e7")
mcp_pinchtab_action(kind="press", ref="e9", key="Enter")
```

Action kinds:
| Kind | Description |
|------|-------------|
| `click` | Click on element |
| `fill` | Type text into an input |
| `select` | Choose an option in a `<select>` |
| `check` / `uncheck` | Toggle a checkbox |
| `hover` | Hover over element |
| `press` | Press a keyboard key on an element |

Workflow:
1. Call `mcp_pinchtab_snapshot` to get element refs.
2. Call `mcp_pinchtab_action` with the ref and desired action kind.

---

### `mcp_pinchtab_text` — Extract page text

Extract all visible text from the current page.

```
mcp_pinchtab_text()
```

- Returns cleaned plain text without markup.
- Use for reading articles, summarising content, or extracting data.

---

### `mcp_pinchtab_screenshot` — Take a screenshot

Capture a screenshot of the current viewport.

```
mcp_pinchtab_screenshot()
```

- Returns a base64-encoded PNG image.
- Use when visual layout matters or to confirm a visual state.

---

### `mcp_pinchtab_pdf` — Generate a PDF

Save the current page as a PDF.

```
mcp_pinchtab_pdf()
```

- Returns the PDF as base64-encoded bytes or saves it to a path.
- Useful for archiving or sharing page content.

---

### `mcp_pinchtab_evaluate` — Run JavaScript

Execute arbitrary JavaScript in the page context and return the result.

```
mcp_pinchtab_evaluate(script="document.title")
mcp_pinchtab_evaluate(script="window.scrollTo(0, document.body.scrollHeight)")
mcp_pinchtab_evaluate(script="JSON.stringify(window.__APP_STATE__)")
```

- Useful for reading internal state, scrolling, or triggering page-level JS APIs.
- Returns the serialised return value of the script.

---

### `mcp_pinchtab_cookies` — Read cookies

Get cookies from the current page or a specific domain.

```
mcp_pinchtab_cookies()
mcp_pinchtab_cookies(domain="example.com")
```

- Returns a list of cookie objects (name, value, domain, path, expires, etc.).
- Useful for session inspection or debugging auth flows.

---

### `mcp_pinchtab_tabs` — Manage tabs

List, switch, open, or close browser tabs.

```
mcp_pinchtab_tabs(action="list")
mcp_pinchtab_tabs(action="new", url="https://example.com")
mcp_pinchtab_tabs(action="select", tabId=2)
mcp_pinchtab_tabs(action="close", tabId=2)
```

Tab actions:
| Action | Description |
|--------|-------------|
| `list` | List all open tabs with IDs and titles |
| `new` | Open a new tab, optionally at a URL |
| `select` | Switch to a tab by ID |
| `close` | Close a tab by ID |

---

## Common Patterns

### Read an article

```
1. mcp_pinchtab_navigate(url="https://example.com/article")
2. mcp_pinchtab_text()  → summarise or extract
```

### Fill and submit a form

```
1. mcp_pinchtab_navigate(url="https://example.com/login")
2. mcp_pinchtab_snapshot()  → find input refs
3. mcp_pinchtab_action(kind="fill", ref="e4", value="user@example.com")
4. mcp_pinchtab_action(kind="fill", ref="e6", value="password")
5. mcp_pinchtab_action(kind="click", ref="e8")  → submit button
```

### Click a link from a snapshot

```
1. mcp_pinchtab_snapshot()
2. mcp_pinchtab_action(kind="click", ref="e12")
3. mcp_pinchtab_text()  → read the new page
```

### Capture a visual state

```
1. mcp_pinchtab_navigate(url="https://example.com/dashboard")
2. mcp_pinchtab_screenshot()  → inspect layout
```

### Run JS to read internal app data

```
1. mcp_pinchtab_navigate(url="https://example.com/app")
2. mcp_pinchtab_evaluate(script="JSON.stringify(window.__store__.getState())")
```

### Work with multiple tabs

```
1. mcp_pinchtab_tabs(action="list")  → get tab IDs
2. mcp_pinchtab_tabs(action="new", url="https://other.com")
3. mcp_pinchtab_tabs(action="select", tabId=3)
4. mcp_pinchtab_text()
5. mcp_pinchtab_tabs(action="close", tabId=3)
```

---

## Security Notes

- PinchTab defaults to `127.0.0.1` and restricts browsing to locally hosted sites via IDPI.
- To browse public websites, configure PinchTab's IDPI allowlist.
- Avoid passing raw user-provided scripts to `mcp_pinchtab_evaluate` without validation.
