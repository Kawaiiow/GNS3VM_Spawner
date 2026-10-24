# NetLab Frontend

Web frontend for **NetLab**, a self-service platform for practicing network engineering on [GNS3](https://www.gns3.com/) labs running on AWS. Students launch their own GNS3 instances, instructors publish exercises, and admins manage accounts. The UI is in Thai.

Built with SvelteKit 5, Tailwind CSS 4, plain JavaScript (no TypeScript), and [Bun](https://bun.sh).

## Getting started

Requires Bun and a running NetLab backend API.

```bash
bun install
cp .env.example .env   # set BACKEND_URL
bun run dev
```

Open <http://localhost:5173>.

| Variable | Default | Description |
| --- | --- | --- |
| `BACKEND_URL` | `http://localhost:8000` | Base URL of the backend API. Server-side only, never exposed to the browser. |

| Script | Description |
| --- | --- |
| `bun run dev` | Dev server with hot reload |
| `bun run build` | Production build into `build/` |
| `bun run preview` | Preview the production build |

## Roles

| Role | Landing page | Can do |
| --- | --- | --- |
| Student | `/dashboard` | Create, start, stop, extend, delete a sandbox instance or an exercise instance |
| Instructor | `/instructor/dashboard` | Everything a student can, plus create and delete exercises |
| Admin | `/admin/dashboard` | Create, edit, delete user accounts |

`dashboardPath(role)` in `src/lib/server/session.js` decides where each role lands after sign-in.

## Pages

| Route | Who | What it does |
| --- | --- | --- |
| `/` | Public | Landing page: intro video, feature list, and links to sign in. Signed-in users are redirected to their dashboard. |
| `/signin` | Public | Username and password form. On success, sets the session cookies and redirects by role. |
| `/signout` | Signed in | POST-only endpoint (no UI). Logs out on the backend, clears cookies, returns to `/`. |
| `/profile` | Signed in | Shows name, username, member ID, role, join and last-active dates, and whether a sandbox or exercise instance is active. |
| `/dashboard` | Student | Two `InstanceCard`s (Sandbox and Exercise) plus a table of open exercises. Pressing **ทำ** on an exercise creates an instance for it. Only one exercise instance at a time. Cards show an expiry time and a button to reset it. |
| `/instructor/dashboard` | Instructor | Same cards and exercise table as the student page, but with no expiry timer. Adds **เพิ่มแบบฝึกหัด** (enabled only when the sandbox is ready) and a delete button on each exercise. |
| `/instructor/exercise/create` | Instructor | Form with title, description, and a checklist of GNS3 projects read from the instructor's sandbox (`?instance_id=`). Each checked project becomes part of the exercise. |
| `/admin/dashboard` | Admin | Table of all users with role, Sandbox and Exercise status badges, and public IPs. Add, edit, or delete accounts. Your own row cannot be edited or deleted here. Refreshes every 5 seconds. |
| `/admin/account/create` | Admin | Create-account form (username, member ID, password, first and last name, role). |
| `/admin/account/update` | Admin | Same form prefilled from `?user_id=`. Leave the password empty to keep it unchanged. |
| Error page | Any | Custom 404 and 503 views. Any other status falls back to the 503 view. |

### The instance card

`InstanceCard` is the main piece of UI. Once an instance exists and is ready, it shows state, a link to the GNS3 web UI (`http://<public_ip>:3080`), the GNS3 username, and a password field that is click-to-copy with a show/hide toggle. Buttons: start or stop, delete (with confirmation), and reset time (only on timed cards while running).

### Auto-refresh

Several pages poll the backend so state stays current without a manual reload:

- `InstanceCard`: every 3 seconds, only while an instance is starting or waiting for a public IP.
- `ExerciseTable`: every 3 seconds while the tab is visible.
- Admin dashboard: every 5 seconds while the tab is visible.

## Project structure

```
src/
├── app.html                 # HTML shell (favicon, body classes)
├── app.css                  # Tailwind entry and global styles
├── env.js                   # Env schema (BACKEND_URL with default)
├── lib/
│   ├── confirm.js           # use:enhance helper that asks for confirmation first
│   ├── components/
│   │   ├── Navbar, Footer   # Page chrome
│   │   ├── Button, Field    # Basic form building blocks
│   │   ├── FormPage         # Wrapper for single-form pages
│   │   ├── AccountForm      # Shared by admin create and update pages
│   │   ├── InstanceCard     # One GNS3 instance: state, IP, actions
│   │   └── ExerciseTable    # Exercise list
│   └── server/              # Server-only code (cannot be imported by client code)
│       ├── api.js           # fetch wrapper for the backend
│       ├── instances.js     # Shared instance actions and dashboard loader
│       └── session.js       # Cookie checks and role redirects
└── routes/
    ├── +layout.server.js    # Exposes signedIn and username to every page
    ├── +error.svelte        # Error page
    ├── +page.svelte         # Public landing page
    ├── signin/              # Login form action
    ├── signout/             # POST-only endpoint, clears cookies
    ├── profile/             # Current user's info
    ├── dashboard/           # Student dashboard
    ├── instructor/
    │   ├── dashboard/       # Instances plus exercise management
    │   └── exercise/create/ # Pick GNS3 projects, create an exercise
    └── admin/
        ├── dashboard/       # User list
        └── account/
            ├── create/
            └── update/      # Takes ?user_id=
static/                      # Fonts, images, animations
```

Each route folder follows the SvelteKit convention: `+page.server.js` holds the `load` function and form `actions`, and `+page.svelte` renders the UI.

The alias `#lib/*` maps to `src/lib/*` (set in `package.json` `imports`).

## How things work

### Talking to the backend

All backend calls go through `src/lib/server/api.js`:

- `api(event, path, { method, body, timeout })` sends JSON, forwards the `access_token` cookie, and has a 10 second default timeout. Network failures become a `503` error page.
- `getJson(event, path)` is for `load` functions. A backend `401` or `403` becomes a `404` page, so users never learn that a protected route exists. Any other failure becomes a `500`.

Use `api` in form actions, where you want to inspect `response.ok` and return `fail(400, { message })`. Use `getJson` in `load`.

### Auth and session

1. `signin` posts credentials to the backend's `/auth/login`.
2. On success, `access_token`, `username`, and `role` are stored as HTTP-only cookies for 24 hours.
3. `redirectIfSignedIn` keeps signed-in users away from `/` and `/signin`.
4. Access control is enforced by the backend. The frontend only chooses where to send each role.
5. `signout` calls `/auth/logout`, then deletes the three cookies.

### Instance actions

`dashboard` and `instructor/dashboard` share `instanceActions` from `src/lib/server/instances.js` (`create`, `start`, `stop`, `extend`, `delete`) and the `loadDashboard` loader, which fetches `/instances` and `/exercises` in parallel. `start` has a 150 second timeout because booting an instance is slow.

`InstanceCard.svelte` polls with `refreshAll()` every 3 seconds while an instance is starting or waiting for a public IP, and stops once it is ready.

### Forms

Forms are plain `<form method="POST" action="?/name">` enhanced with `use:enhance`. Destructive actions wrap `use:enhance` with `confirmed(message)` from `src/lib/confirm.js`. Errors come back as `fail(400, { message })` and are shown from the `form` prop.

## Adding a page

1. Create `src/routes/<path>/+page.server.js` with a `load` (use `getJson`) and optional `actions` (use `api`).
2. Create `+page.svelte` that reads `data` and `form`.
3. If the page is role-specific, link to it from the right dashboard or from `Navbar.svelte`.
4. Reuse `FormPage`, `Field`, and `Button` for form pages, and keep Thai user-facing messages consistent with the existing ones.

## Conventions

- JavaScript only, 4-space indentation, single quotes.
- Backend access stays in `src/lib/server/`. Never call `BACKEND_URL` from client code.
- Tailwind utility classes only, no separate component CSS.
- Shared server logic (like instance actions) goes in `src/lib/server/`, not duplicated across routes.