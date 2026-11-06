# Current RMS Warehouse Webhook Tester

This standalone Windows tester receives Current RMS webhooks. During the one-screen
notification pilot it can also relay them to the Manager Pi over the local network.

## Start it

Double-click `Current RMS Webhook Tester.vbs` in the project root. The application:

1. reads the Current RMS connection from `manager_data/settings.json`;
2. starts a receiver bound only to `127.0.0.1:8787`;
3. starts an outbound Cloudflare quick tunnel when requested;
4. creates or updates only webhooks whose names start with
   `Warehouse Webhook Tester`;
5. records deliveries in `webhook_test_data/events.jsonl`.

The API key and callback token are not committed. The entire `webhook_test_data/`
folder is ignored by Git.

## Testing workflow

1. Keep the application open.
2. Confirm that the tunnel status says `Online`.
3. Select the events to test.
4. Click `Create/update selected test webhooks`.
5. Make a test job or item change in Current RMS.
6. Inspect the event row and full JSON payload in the application.

## One-screen notification pilot

1. Update the Manager Pi and the selected test dashboard to version 2.4.16.
2. In the PC remote manager, open `Notifications` and choose one screen under
   `Webhook Notification Pilot`.
3. Enable the pilot, save it, and copy the displayed `Tester forwarding URL`.
4. Paste that URL into `Manager Pi test-screen relay` in this tester.
5. Tick `Forward received webhooks to the Manager Pi` and save the relay settings.

The selected screen then receives webhook-built notifications. Scheduled API
refreshes continue to update all dashboard data, but polling-built notifications are
not sent to that screen, preventing a second copy of the same popup. Other screens
remain on their existing notification path during the pilot.

The tester includes all 159 events documented in the official Current RMS webhook
collection, grouped by friendly labels and searchable in both the registration and
visible-event sections. This covers Activity, Discussion, Document Layout, Erase,
Export, Import, Invoice, Item, Member, Opportunity, Purchase Order, Project,
Quarantine, Rate Definition, and Stock Level events.

Use `Add an event not listed in the official catalogue` only if Current RMS adds a
new event before the tester catalogue is updated. The custom choice is saved on this
PC and appears in both the registration choices and the visible-event filters. It is
not registered until `Create/update selected test webhooks` is clicked. Removing a
saved custom choice does not silently delete a webhook that was already registered
in Current RMS.

Use the separate `Visible event types` checkboxes to hide events from the on-screen
list. This only changes the display: hidden events are still received, deduplicated,
and written to the local event log. The visibility choices are remembered after the
application restarts and do not change which webhooks are registered in Current RMS.

Use `Send local sample event` to verify the local receiver without changing Current
RMS. Use `Remove tester webhooks` when the test is finished. That action deletes only
the tester-owned hooks and leaves all other Current RMS webhooks unchanged.

The quick-tunnel URL changes when a new tunnel is created. After restarting the
application, start the tunnel and click `Create/update selected test webhooks` again
to point the existing tester hooks at the new URL.

## Tests

```powershell
.venv\Scripts\python.exe -m unittest webhook_tester.test_app -v
```
