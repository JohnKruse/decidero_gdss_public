# Frontend & Template Development Guide

This guide is for developers who are extending, forking, or contributing to Decidero GDSS. It
explains the conventions for adding new pages and UI components so that the look, feel, and
navigation remain coherent.

---

## Table of Contents

1. [Template conventions](#1-template-conventions)
2. [Adding a new page — step by step](#2-adding-a-new-page--step-by-step)
3. [Role system](#3-role-system)
4. [Header protection model](#4-header-protection-model)
5. [Quick Actions dashboard pattern](#5-quick-actions-dashboard-pattern)
6. [CSS and design system](#6-css-and-design-system)
7. [Context variables reference](#7-context-variables-reference)
8. [Common mistakes to avoid](#8-common-mistakes-to-avoid)

---

## 1. Template conventions

### Every authenticated page MUST extend `_base.html`

```jinja
{% extends "_base.html" %}
```

Extending `_base.html` gives you for free:

| Inherited element | What it provides |
|---|---|
| Site header | Welcome name, My Profile, Dashboard, Logout — always visible |
| Favicons | All sizes + web manifest |
| Base stylesheets | `dashboard.css`, `components.css`, `layout_v2.css` |
| `reliable_actions.js` + `page_utils.js` | Client-side utilities loaded on every page |
| Site footer | About · GitHub · License links |
| `grab.js` | Conditionally loaded when the Grab extension is enabled |
| `data-user-role` | Attribute on `.layout-container` for role-based CSS or JS |

### The `{% block %}` contract

| Block | Purpose | Notes |
|---|---|---|
| `{% block title %}` | `<title>` tag content | Always override — default is just "DECIDERO GDSS" |
| `{% block extra_css %}` | Additional `<link>` tags | Load your page-specific CSS here |
| `{% block content %}` | Main page content inside `<main>` | Everything visible goes here |
| `{% block extra_js %}` | Additional `<script>` tags | Load your page-specific JS here |
| `{% block top_nav_right %}` | Extra items appended to the right side of the header | Rarely needed; use sparingly |

**Never put layout structure outside these blocks.** Adding raw HTML outside a block in a child
template causes Jinja2 to ignore it silently.

### Pages that intentionally do NOT extend `_base.html`

`login.html` and `register.html` are standalone templates by design — they have their own
full-screen layouts and don't need the authenticated header. If you need a public-facing page with
no navigation header, write it as a standalone template. **Do not** extend `_base.html` and then
try to hide the header.

---

## 2. Adding a new page — step by step

### Step 1: Create the template

Create `app/templates/your_page.html`:

```jinja
{% extends "_base.html" %}

{% block title %}Your Page Title - Decidero{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="/static/css/your_page.css">
{% endblock %}

{% block content %}
<div class="layout-grid">
    <section class="layout-card">
        <h2>YOUR PAGE HEADING</h2>
        <!-- page content -->
    </section>
</div>
{% endblock %}

{% block extra_js %}
<script src="/static/js/your_page.js"></script>
{% endblock %}
```

### Step 2: Add the route

Add your route to `app/routers/pages.py`. Pass at minimum `request`, `current_user`, `role`,
and `UserRole` in the template context.

**Simple authenticated page (any logged-in user):**

```python
@router.get("/your-path", response_class=HTMLResponse, response_model=None)
async def your_page(
    request: Request,
    current_user: User = Depends(get_current_active_user),
):
    """Brief description of the page."""
    return templates.TemplateResponse(
        request,
        "your_page.html",
        {
            "request": request,
            "current_user": current_user,
            "role": current_user.role,
            "UserRole": UserRole,
        },
    )
```

**Facilitator/admin-only page** (pattern used by Meeting Designer and Activity Library):

```python
@router.get("/your-path", response_class=HTMLResponse, response_model=None)
async def your_page(
    request: Request,
    current_user: User = Depends(get_current_active_user),
):
    """Description — requires facilitator/admin."""
    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(status_code=500, detail="Authenticated user not available.")
        current_user = cached_user
    if current_user.role not in [UserRole.FACILITATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=403, detail="Facilitators and admins only.")

    return templates.TemplateResponse(
        request,
        "your_page.html",
        {
            "request": request,
            "current_user": current_user,
            "role": current_user.role,
            "UserRole": UserRole,
        },
    )
```

**Important — route ordering:** If you add a route under `/meeting/`, place it **before** the
`/meeting/{meeting_id}` catch-all route in `pages.py`, otherwise the catch-all will match first
and your route will never be reached.

### Step 3: Add CSS

Create `app/static/css/your_page.css`. Follow the existing design system (see
[CSS and design system](#6-css-and-design-system) below).

### Step 4: Add JavaScript

Create `app/static/js/your_page.js`. Use `cache-busting` query strings on the `<script>` tag
during active development (`your_page.js?v=2`).

### Step 5: Add a navigation entry point

New facilitator/admin tools should be discoverable from the **Quick Actions panel on the
dashboard**, not from a global header link. See
[Quick Actions dashboard pattern](#5-quick-actions-dashboard-pattern) below.

---

## 3. Role system

### Role values

| Role | `role.value` | Can do |
|---|---|---|
| `participant` | `"participant"` | Join and participate in meetings |
| `facilitator` | `"facilitator"` | Create/manage meetings, use AI tools |
| `admin` | `"admin"` | All facilitator actions + manage users |
| `super_admin` | `"super_admin"` | All admin actions + system-level settings |

### Role checks in Python (routes)

```python
from app.models.user import UserRole

# Single role check
if current_user.role not in [UserRole.FACILITATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN]:
    raise HTTPException(status_code=403, detail="...")

# Admin-only
if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
    raise HTTPException(status_code=403, detail="...")
```

### Role checks in Jinja2 templates

Always use `current_user.role.value` — **not** `str(current_user.role)`.

```jinja
{# CORRECT — role.value gives "facilitator" #}
{% if current_user.role.value in ['facilitator', 'admin', 'super_admin'] %}

{# WRONG — str() gives "UserRole.FACILITATOR" which never matches #}
{% if current_user.role|string|lower in ['facilitator', 'admin', 'super_admin'] %}
```

The `data-user-role` attribute on `.layout-container` is set correctly by `_base.html` using
`current_user.role.value` and can be targeted from JavaScript:

```javascript
const role = document.querySelector('.layout-container')?.dataset.userRole;
if (role === 'facilitator' || role === 'admin' || role === 'super_admin') { ... }
```

---

## 4. Header protection model

The header in `_base.html` is **deliberately placed outside any `{% block %}`**. This means:

- Child templates **cannot** override or remove it — Jinja2 has no mechanism to do so.
- Any template that extends `_base.html` **always** shows Welcome / My Profile / Dashboard / Logout.
- The only way to omit the header is to write a standalone template (as `login.html` does).

This is the primary defence against accidental UX regressions. If you are extending Decidero and
find yourself wanting to hide the header on an authenticated page, reconsider the design — the
header is always expected to be there.

---

## 5. Quick Actions dashboard pattern

New tools for facilitators and admins should be added as buttons in the **Quick Actions panel** in
`app/templates/dashboard.html`, not as global header links.

### Flat button (standalone action)

```html
<button
    class="action-btn"
    type="button"
    data-requires-role="facilitator"
    onclick="navigateTo('/your-path')"
>
    YOUR ACTION
</button>
```

### Grouped buttons with a label

When two or more buttons represent parallel paths to the same goal, wrap them in a
`.meeting-create-group`:

```html
<div class="meeting-create-group">
    <span class="meeting-create-group__label">Group Label</span>
    <div class="meeting-create-group__buttons">
        <button class="action-btn" type="button" onclick="navigateTo('/path-a')">OPTION A</button>
        <button class="action-btn" type="button" onclick="navigateTo('/path-b')">OPTION B</button>
    </div>
</div>
```

### Alignment across groups

When a labeled group sits next to standalone buttons, the label adds height that makes the button
rows misalign. Fix this by wrapping the standalone buttons in a **ghost group** (same structure,
invisible border and background):

```html
<div class="meeting-create-group meeting-create-group--ghost">
    <span class="meeting-create-group__label" aria-hidden="true">&nbsp;</span>
    <div class="meeting-create-group__buttons">
        <button class="action-btn" type="button" onclick="navigateTo('/another-path')">
            STANDALONE ACTION
        </button>
    </div>
</div>
```

The ghost's `&nbsp;` label spacer exactly matches the height of the real label, keeping all button
rows on the same baseline.

---

## 6. CSS and design system

All pages share a common design vocabulary. Use CSS custom properties; do not hard-code colours.

### Colour palette

```css
--navy-blue:   #0B3D91   /* primary brand colour — buttons, headings, borders */
--white:       #FFFFFF   /* backgrounds */
--nasa-red:    #FF0000   /* errors, logout, destructive actions */
--silver:      #C0C0C0   /* secondary buttons, inactive elements */
--light-blue:  #7EC0EE   /* join / participant actions */
--gold:        #FFD700   /* manage / admin actions */
```

### Typography

Font: **Jost** (loaded via Google Fonts in `dashboard.css`). Use `font-weight: 500` for labels,
`600` for headings.

### Layout primitives

| Class | What it does |
|---|---|
| `.layout-grid` | Top-level page grid — wraps all content sections |
| `.layout-card` | White card with shadow — the standard content container |
| `.action-btn` | Navy blue action button |
| `.view-btn` | Silver secondary button |
| `.manage-btn` | Gold admin button |
| `.logout-btn` | Red destructive button |
| `.filter-chip` | Pill-shaped toggle filter |
| `.status-pill` | Coloured status badge |

### Page-specific CSS

Create a separate `app/static/css/your_page.css` file and load it in `{% block extra_css %}`.
Do not add page-specific rules to `dashboard.css` — that file is the shared design system.

---

## 7. Context variables reference

The following variables are available in all templates rendered from authenticated routes:

| Variable | Type | Description |
|---|---|---|
| `request` | `Request` | FastAPI request object (required by Jinja2 `TemplateResponse`) |
| `current_user` | `User` | The authenticated user model |
| `current_user.role` | `UserRole` (Enum) | User's role — use `.value` in templates |
| `current_user.first_name` | `str` | Display name shown in header |
| `role` | `UserRole` | Alias for `current_user.role` |
| `UserRole` | class | The `UserRole` enum — use for comparisons in templates |

Additional context passed by specific routes only:

| Variable | Passed by | Description |
|---|---|---|
| `ui_refresh` | Dashboard, Admin/Users | UI auto-refresh config dict |
| `brainstorming_limits` | Meeting page | Max ideas/comments config |
| `meeting_refresh` | Meeting page | Meeting polling config |
| `frontend_reliability` | Meeting page | Connection retry config |

The `_base.html` template handles absent optional variables gracefully (uses `if var else ''`
fallbacks), so most new pages do not need to pass `ui_refresh`.

---

## 8. Common mistakes to avoid

| Mistake | Consequence | Fix |
|---|---|---|
| Not extending `_base.html` | Page missing header, favicons, base CSS, footer | Start with `{% extends "_base.html" %}` |
| Using `str(current_user.role)` in templates | Role check always fails (produces `"UserRole.FACILITATOR"`) | Use `current_user.role.value` |
| Adding HTML outside a `{% block %}` | Jinja2 silently ignores it | Put all content inside the appropriate block |
| Adding a `/meeting/your-path` route after the catch-all | Route never reached | Place new routes **before** `/meeting/{meeting_id}` in `pages.py` |
| Adding nav links to `_base.html` header | Header gets cluttered; links show on every page | Add navigation buttons to the Quick Actions panel in `dashboard.html` instead |
| Duplicating the header in a new template | Header diverges from base over time | Extend `_base.html` instead |
