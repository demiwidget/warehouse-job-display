# Warehouse Job Display

A full-screen warehouse signage system that maps Current-RMS jobs to warehouse areas and displays them on public display routes.

## Features

- Admin dashboard for area management, job mapping, and display settings.
- Public display pages at `/display/:areaId` for TVs/warehouse screens.
- Local admin authentication (session cookie based).
- Automatic job detail refresh from Current-RMS.
- Display-mode keyboard shortcuts:
  - `F` toggle fullscreen
  - `R` refresh all display data
  - `T` toggle dark/light theme
  - `H` or `?` open shortcut help
  - `Esc` close shortcut help

## Tech Stack

- React + Vite + TypeScript
- Express + tRPC
- Drizzle ORM + MySQL
- Tailwind CSS + shadcn/ui

## Prerequisites

- Node.js 20+
- pnpm 10+
- MySQL database
- Current-RMS API credentials (for live integration)

## Environment Variables

Create a `.env` file with:

```bash
DATABASE_URL=mysql://user:password@localhost:3306/warehouse_display
SESSION_SECRET=replace-with-strong-random-string
CURRENT_RMS_API_KEY=your-api-key
CURRENT_RMS_SUBDOMAIN=your-subdomain
```

## Local Development

1. Install dependencies:

   ```bash
   pnpm install
   ```

2. Generate/apply database migrations:

   ```bash
   pnpm db:push
   ```

3. Start the app:

   ```bash
   pnpm dev
   ```

4. Open:
   - Home/Login: `http://localhost:3000/`
   - Admin: `http://localhost:3000/admin`
   - Display: `http://localhost:3000/display/1`

## Testing and Checks

```bash
pnpm check
pnpm test
pnpm build
```

## Deployment

1. Build production assets:

   ```bash
   pnpm build
   ```

2. Run production server:

   ```bash
   pnpm start
   ```

3. Recommended deployment setup:
   - Run behind Nginx/Caddy reverse proxy.
   - Use HTTPS and secure cookie settings.
   - Use process manager (systemd/PM2/Docker restart policy).
   - Ensure persistent MySQL and backups.

## Screen Deployment Tips

- Use one URL per screen (`/display/:areaId`).
- Put browser in kiosk/fullscreen mode.
- Use the `F` shortcut for fullscreen after page load.
- Set refresh interval per area in admin settings.
