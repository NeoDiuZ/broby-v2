# Synthetic mapping-correction acceptance

Use `scripts/smoke-transfer-corrections.py` against the fixed, isolated V2 frontend.
It requires an existing organization-master credential file containing `username`
and `password`. It creates two new **SYNTHETIC** clinics, patients, owners, generated
WAV audio, test medication history, native lab facts and text files. Existing clinic
clinical records and organization policy are not edited. No messages or speech
provider calls are made. Leave the fixtures as evidence; the script does not delete
medical copies.

Use the same private state file for each phase. It contains owner capabilities and
synthetic review snapshots and is created with mode 0600. Never publish it or paste
its owner capability into release notes. The command output contains check labels,
not credentials, owner links or response bodies.

```sh
python scripts/smoke-transfer-corrections.py \
  --credentials /private/path/v2-credentials.json \
  --state /private/path/correction-run.json --phase prepare
```

1. **Prepare** uses API calls to establish a deliberately old link in the new
   receiving clinic. This is synthetic setup, not browser acceptance evidence.
   Open `owner_url` from the private state file in the browser. Choose
   `target_clinic_name`, opt into structured medication history, original audio and
   correction of the receiving patient link, then consent and request the transfer.
2. Run the same command with **`--phase review`**. In the staff browser, choose the
   new receiving clinic → Settings → Data & migration → Review transfer → Review a
   patient-link correction. Select the `SYNTHETIC corrected receiving patient`,
   load its review, and inspect both identities, all owners and both histories.
3. Before accepting that browser review, run **`--phase stale`**. The script updates
   only its synthetic additional owner's name and verifies that API acceptance with
   the old digest returns 409 without importing anything. Try the already-loaded
   browser review, record its stale error, reload, and verify that its reason and
   acknowledgements reset. Review again, enter a reason and explicitly confirm
   corrected identity and unresolved history before accepting in the browser.
4. Run **`--phase readback`**. It verifies preserved records and exact old media,
   native PostgreSQL history, reviewer/digest/consent/fingerprint receipts, exact new
   copies, private unresolved notices on both patients, stock invariance, and a
   normal subsequent request with no duplicate writes. It never submits a successful
   mapping correction itself. Check both patient banners in the browser, including
   with timeline filters applied, and record that evidence separately.

`readback` can be rerun. Review may be repeated before acceptance. `prepare` refuses
to reuse an existing state file, and the one-time `stale` probe must be preceded by
`review`. If the fresh review changes again, rerun `review` before browser acceptance.
Run another `review` before another deliberate stale test. A partially failed setup
retains its private state for investigation rather than silently creating another
fixture. The script does not assert clinical fact equivalence or clear the unresolved
reconciliation gate.

For a disposable local V2 password-mode fixture only, pass its loopback base URL and
`--allow-local-test`. Other remote hosts are rejected to protect original Broby.
