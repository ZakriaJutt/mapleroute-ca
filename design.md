# Design brief — MapleRoute console

**Question this file answers:** what should each screen look and feel like?

Screens are listed in [App-flow.md](App-flow.md#screen-and-route-inventory). Sizes, colours and timings are author proposals. WCAG 2.2 criteria `[S: SRC-23]` are named as targets; none has been tested.

## Principles

1. **State what a claim rests on, next to the claim.** Every status and every report line shows its evidence grade (EG-1 to EG-5, [Decision.md](Decision.md#43-evidence-grades)).
2. **A rejection is a normal, legible result**, not an error page. It says what was asked, why it was refused, and that nothing was sent.
3. **Never show a secret twice. Never show content at all.**
4. **Plain words.** "Not eligible", "Not evidenced", "Not collected". The word "proof" does not appear in the interface.

## Visual hierarchy and layout

- Left navigation (220 px): Projects, Reports, Evidence, Settings; project sub-navigation appears inside a project: Overview, Connections, Routes, API keys, Requests, Alerts. Operator navigation is a separate set and a different header colour so the founder cannot mistake the mode.
- Content column up to 1,120 px. One primary action per screen, top right.
- Page title, then one sentence saying what the screen is for, then the table or form.
- Tables are the main component: fixed header, sortable columns, row detail on a separate route rather than in a pop-over.

## Typography and colour

| Token | Value | Use |
|---|---|---|
| Font | System UI stack; monospace for identifiers, request IDs and hashes | — |
| Base size | 16 px body, 14 px table cells, 24 px page title; line height 1.5 | Text resizes to 200% without loss (1.4.4) |
| Ink | `#1B1F24` on `#FFFFFF` | Contrast above 4.5:1 (1.4.3) |
| Accent | `#0B5CAD` | Links, primary button |
| Eligible, verified | `#1A6B3C` with a check icon and the word | Never colour alone (1.4.1) |
| Unverified, withheld | `#8A5A00` with a clock icon and the word | |
| Suspended, not eligible, rejected | `#A32020` with a stop icon and the word | |
| Draft | Grey dashed border and the word "Draft" | |
| Focus ring | 3 px `#0B5CAD` outline, 2 px offset | Visible on every control (2.4.7), not hidden by the sticky header (2.4.11) |

Controls are at least 24 × 24 CSS px (2.5.8). Component boundaries and icons reach 3:1 (1.4.11).

## Components

| Component | Behaviour |
|---|---|
| Status chip | Icon + word + optional grade, e.g. "Verified · EG-3 · checked 09:12" |
| Grade badge | "EG-1" to "EG-5" with the grade's name on hover and focus, and always spelled out in the report |
| Secret field | Masked; paste allowed; cleared on save and on error; never pre-filled |
| Show-once panel | Key in monospace, Copy button, "You will not see this key again", and a Done button that removes it |
| Confirm-by-typing dialog | For delete connection, delete organisation, approve allow-list; focus trapped inside, Escape cancels, focus returns to the trigger (2.1.2) |
| Status region | `role="status"` for progress, `role="alert"` for failures (4.1.3) |
| Reason line | Under every non-eligible or rejected item: one sentence in the provider's own terms |
| Empty state | One sentence of meaning and one action |

## Principal screens

**S-06 Routes.** Title "Routes". Sentence: "Only verified routes receive requests. Everything else is rejected." Primary button "Bind a model". Table one, "Bound": Alias · Provider · Identifier (monospace) · Class · Destinations (region chips) · Status chip · Last check · link "Record". Below, table two, "Available in this connection but not eligible": Identifier · Destinations reported · Reason line. A suspended route puts a red banner above both tables: "Suspended at 14:02. The provider now reports us-east-1 among the destinations."

**S-08 Request log.** Filter bar (range, decision, code, alias, key), result count, Export. Columns: Time · Request ID · Alias · Route · Decision chip · Code · Status · Latency · Tokens · Provider region. The last column reads "ca-central-1 · EG-2", "Not collected" or "Not available for this provider". Rejected rows are not red-filled; the chip carries the state.

**S-10 Report view.** A cover block: tenant, period, allow-list versions, file hash. Then five sections in fixed order: Inference, Request and response logs, Backups, Storage, Subprocessors. Each section is a table: Statement · Count or value · Grade · Source and date. A final section, always present, titled "Not evidenced", lists what nobody outside the provider can show. If the statement is withheld the cover block is replaced by an amber panel that says why.

**S-05 Connections (AWS form).** Two columns: left, the form; right, a panel "What this access allows" with two lists, "MapleRoute can" and "MapleRoute cannot". The policy template is in a copyable code block.

**S-14 Allow-list approval.** Side-by-side diff of active and draft versions, removed routes in red with strike-through and the word "Removed", added in green with "Added". Under it: tenants affected, count of bindings that will stop. Step two asks for the version number typed in full.

**S-12 Availability map.** Public, printable on one page. Columns: Provider · Model · In Canada? · Route · Destinations · Source and date. The caveat line sits directly under the title, same size as body text, not a footnote.

## Responsive behaviour

- Above 1,024 px: navigation and content side by side.
- 640–1,024 px: navigation collapses to a top bar; tables keep four columns (first, status, time, action) and move the rest into the row's detail route.
- Below 640 px: everything remains usable. Forms, including S-05 with its secret fields, become one column with the "What this access allows" panel above the form; code blocks wrap. Content reflows at 320 CSS px (a 1,280 px window at 400% zoom) without two-direction scrolling; only data tables scroll sideways, under the 1.4.10 exception for two-dimensional content.

## Interaction feedback

- A button that starts work becomes disabled and shows its progress text within 100 ms.
- Long work (verification up to 30 s, export, report) reports in a status region; the page stays usable.
- After a failed submit, focus moves to an error summary at the top of the form that links to each field (3.3.1, 2.4.3); each field repeats its message in text (3.3.3).
- Nothing auto-dismisses in under 20 seconds; the session warning allows extension (2.2.1).

## Microcopy

| Situation | Text |
|---|---|
| Pending operation | "Asking AWS which Regions this profile can use. This usually takes a few seconds. No requests are forwarded until it finishes." |
| Recoverable error | "AWS refused the role (AccessDenied on bedrock:GetInferenceProfile). Add that permission from the template on this page, then choose Verify now. Nothing was changed." |
| Human approval (operator) | "You are about to activate allow-list 2026.12.02-1. It removes 1 route used by 3 organisations; their requests on that route will be rejected from activation. Type the version number to approve." |
| Rejection seen in the log | "Rejected: no Canada-listed route is bound to 'claude-sonnet-5-5'. The request was not sent to any provider." |
| Azure line in a report | "Configuration matched at 2,871 checks; 9 checks failed. Longest time requests were served since a matching check: 45 minutes (limit 60). Requests flagged for a configuration change: 0. Not observed between checks." |
| Withheld report | "The residency statement is withheld. One asset in the register has no location evidence." |
| Key shown once | "Copy this key now. You will not see it again." |

## Inspecting evidence, correcting, and drafts versus approved

- **Inspect source evidence.** From any status chip or report line, "Record" opens the verification record: the provider's answer as returned (identifiers and Regions only), the time, the allow-list version, the grade. From a report line, the source column links to the register row or the dated provider page.
- **Correct a suggestion.** The product makes no AI suggestion. The nearest case is a watcher difference, which is a proposal to the operator: it is shown as "Proposed change", may be edited in the draft, and has no effect until approved. A tenant corrects a non-eligible route by changing the deployment in its own cloud and choosing "Verify now"; the console never lets a user overwrite a provider-reported value.
- **Drafts and approved results.** Draft allow-lists: dashed border, "Draft", no version hash. Active: solid, hash shown, approver and time. Reports: `generating` and `failed` runs are never downloadable; `ready` shows the hash; `withheld` shows the reason.

## Accessibility map

Target: WCAG 2.2 level AA. Status: **not tested**. Known gap: data tables below 640 px rely on the 1.4.10 exception and are harder to use on a phone. Forms do not rely on it.

| Criterion | Screens | Manual check |
|---|---|---|
| 2.1.1 Keyboard, 2.1.2 No Keyboard Trap | S-05, S-06, S-07, S-14 dialogs | Complete connect → bind → create key → revoke with keyboard only; Escape leaves every dialog |
| 2.4.3 Focus Order, 2.4.7 Focus Visible, 2.4.11 Focus Not Obscured | All; sticky table headers on S-08 | Tab through a 50-row table; the focused row is never under the header |
| 3.3.1 Error Identification, 3.3.3 Error Suggestion | S-05, S-13 | Submit an invalid role ARN; focus lands on the summary; the message says what format is expected |
| 3.3.2 Labels or Instructions | S-05 secret fields | Each field has a visible label and a hint; placeholder is not the label |
| 3.3.4 Error Prevention | S-13 delete, S-14 approve, S-05 delete connection | Review step lists consequences; confirm-by-typing; delete has a cancel window |
| 3.3.8 Accessible Authentication | S-01 | Sign-in is a provider redirect; MapleRoute adds no puzzle or memorised secret |
| 4.1.2 Name, Role, Value | Status chips, grade badges | Screen reader reads "Status: suspended, grade EG-3" |
| 4.1.3 Status Messages | S-05 test, S-06 verification, S-08 export, S-09 new alert, S-10 generation | Screen reader announces completion without focus moving |
| 1.4.1 Use of Color, 1.4.3 Contrast, 1.4.11 Non-text Contrast | Chips, diff view | Greyscale screenshot still distinguishes every state |
| 1.3.1 Info and Relationships | All tables, report view | Header cells are announced with each data cell |
| 1.4.10 Reflow | S-05, S-07, S-13 forms; S-06, S-08 tables | At 320 px width complete connect and create key without horizontal scrolling; tables may scroll |
| 2.2.1 Timing Adjustable | Session warning | Extend from the warning by keyboard |
| 2.4.2 Page Titled, 2.4.6 Headings and Labels | All | Title names the screen and the project |
