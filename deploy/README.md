# Future VPS deployment checkpoint

The codebase is prepared for a future manual OVH migration, but this repository change does not contact the VPS, Raspberry Pi, Telegram login flow, or Cloudflare.

## Security boundary

- `tg-handler` is the only process allowed to open the Pyrogram session file.
- The API listens inside the container while Docker publishes it only on `127.0.0.1`.
- Cloudflare Tunnel forwards a dedicated hostname to `http://127.0.0.1:8112`.
- Cloudflare Access service-token headers and the application Bearer token are both checked.
- Put all secrets in a root-owned environment file with mode `600`; never commit it.
- Do not run the Raspberry Pi and VPS copies against the same Telegram session simultaneously.

## Manual deployment order

1. Choose the Cloudflare hostname and create an Access application restricted to the OpenClaw service token.
2. Prepare the VPS checkout and a protected `.env`. Keep `TG_READER_REQUIRE_CF_ACCESS=true`.
3. Build without starting the Telegram client:

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.vps.yml build
   ```

4. Back up the Raspberry Pi session and database. Stop the Raspberry Pi service and verify that it remains stopped.
5. Copy the session into `data/sessions`, set the directory to `700` and every session file to `600`. Never log out the session.
6. Start exactly one service:

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
   ```

7. Verify container health and Telegram connection locally on the VPS. Then verify `/v1/status` through Cloudflare with both authentication layers.
8. Point the OpenClaw environment variables at the Cloudflare hostname and restart its Gateway.
9. Run read-only smoke tests first: status, unread, private search, joined-channel search. Test mark-read only on a deliberately chosen dialog after preview and explicit confirmation.
10. Keep the old Raspberry Pi session backup until the VPS has been stable; do not restart the old service.

No hostname is filled in because none was selected during local implementation.
