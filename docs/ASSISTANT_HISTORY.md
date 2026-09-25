# Saved assistant conversations

Ask Broby now saves conversations privately for the current clinic membership.
The drawer's Saved conversations menu restores questions, answers, source
receipts and action results after closing the drawer or reloading the page.
New starts another conversation; another operator or clinic cannot read it.
Historical answers have timestamps and are snapshots. A new question reads the
current records; saved user questions supply conversational context, not facts.

Every question has a stable retry key. The request is recorded before calling
the model, and a five-minute claim prevents parallel duplicate calls. Failed or
interrupted questions can be retried; an obsolete attempt cannot overwrite the
new attempt's answer. Conversations hold up to 100 questions and the picker
shows the latest 50. The existing keyless API remains compatible but does not
save history; the web client always supplies a key.

A saved proposal is confirmed through its stored turn ID, never through fields
submitted by the browser. The shared action executor checks the operator's
current permissions, master locks and record versions. Its stable confirmation
key prevents duplicate mutations after a lost response or reload. Completed
actions remain visible. Pending or stale proposals never execute automatically.
The model's action catalogue applies the same effective permissions and
only advertises actions with documented field contracts. Richer intent
coverage and field contracts for every advanced workflow remain unfinished.
Ten routine operations now use strict proposal schemas and labelled deterministic
reviews, including eight newly advertised actions. Invalid model fields or record
references produce clarification instead of a confirm button. See
[Reviewed assistant operations](ASSISTANT_OPERATIONS.md) for scope and limits.

Read answers and saved Reports views share a validated query contract, including
low-stock/outstanding filters, statuses, clinic-local dates and typed observation
comparisons. See [Assistant queries](ASSISTANT_QUERIES.md). An answer is a snapshot;
a saved view refreshes the same stored filters against current records.

Verification: nine backend scenarios cover private/cross-clinic access, retry
payload mismatch, inactive membership, provider interruption, active claims,
stale result fencing, persisted context, current permissions/master locks,
stale versions, lost action acknowledgement and bounded conversation length.
Run `pytest api/tests/test_assistant_history.py -q`. The complete backend suite,
frontend recording tests, TypeScript and production build are also checked.

Hosted acceptance: open Ask Broby, ask a factual question, reload and restore
it through Saved conversations; ask for a synthetic consultation, confirm,
reload and check the completed action opens that same consultation. Private
API read/confirmation and mutation replay are checked separately. Release
verification evidence is kept in the operator's ignored local evidence folder.

Hosted verification on 24 September: PR #10 merged and both Railway services deployed `1a6790891aaba48592368b779c9a2578bf77f5ab`. Eight real hosted checks passed, including actual AI invoice retrieval/proposal, stable question replay, persisted confirmation and privacy against another authenticated synthetic user. Browser acceptance also created and confirmed a synthetic consultation, reloaded the page and restored its completed action. The synthetic privacy-test membership was deactivated afterward.

When a name matches multiple patients, selecting one now repeats the exact saved
question in the same private conversation with that patient's ID. It preserves
requested filters instead of substituting a generic history question; the normal
scope and permission checks still apply and no action is auto-confirmed.

Dictionary proposal/review guidance opens Settings directly at Observation
catalog. That destination is fixed by the server, persists with the answer, and
retains the existing dedicated human review through the shared action executor.
SQLite/PostgreSQL continuation tests and frontend interaction tests cover these
paths; representative clinical-language acceptance remains separate.
