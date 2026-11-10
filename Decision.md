# Decision — MapleRoute (Canada-only LLM gateway)

**Question this file answers:** can a Canadian software vendor justify paying for MapleRoute, and should the founder spend money finding out?

**Decisive pilot question for the whole repository:** which buyer security requirement remains unmet by existing cloud controls or by Trango's Sovereign AI Gateway? The repository defines eligible routes, fail-closed behaviour, and the evidence available for inference, logs, backups, storage and subprocessors.

Status: planning document. Nobody has interviewed a customer. Willingness to pay is unproven. Nothing here is legal advice.

## How numbers are labelled (used in all ten files)

| Tag | Meaning |
|---|---|
| `[C]` | Stated in the chat or in the research record behind it, received through the decision brief. A price, an offer, a research note or a model input. Every unit-economics input tagged `[C]` is an **assumption** made in the chat's model, not a finding. Research items the brief marked "secondary" are called unverified wherever used. |
| `[S: SRC-nn]` | Read by the author at the named source on 2026-11-10. Source table: [section 13](#13-sources-and-assumptions). A provider's documentation is a statement by that provider. It is never proof of where a request was processed. |
| `[A]` | Assumption made by the author. |
| `[P]` | Proposal by the author on a point not decided in chat. |
| `[D]` | Derived by arithmetic from tagged inputs shown beside it. |

Engineering parameters in the other nine files (timeouts, retention days, hour estimates, sizes) are author proposals; each file says so once instead of tagging every value.

Evidence grades `EG-1` to `EG-5` are defined once in [section 4.3](#43-evidence-grades) and cited by ID elsewhere.

## 1. Proposed decision

**Do not build yet. Spend 90 days and CAD 1,800 testing one question by hand.** `[P]` The CAD 1,800 is the brief's 30-day budget `[C]`, re-timed over 90 days `[P]`. The brief's roadmap separately carries CAD 2,500 `[C]`; which applies is undecided (section 11).

Reasons, in order of weight:

1. Reading the providers' pages on 2026-11-10 shows the confusion is real and worse than the brief said (section 4.1). On Bedrock, 31 model tables show "Geo" inference as supported from `ca-central-1`; the model cards give a Canada-only `ca.` profile for 2 of them. The other 29 route to US Regions `[S: SRC-01, SRC-02]`.
2. The same reading shows the product cannot deliver what most buyers will first ask for. No current Claude Sonnet or Opus model and no GPT-6 model has a pay-per-token Canada-only deployment on Bedrock or Azure today (section 4.1). MapleRoute would block them.
3. Every Canada-only route that exists can be reached and enforced with the customer's own cloud controls (IAM policy, service control policy, Azure Policy) `[S: SRC-04, SRC-06]`. The gap is convenience, upkeep and documentation `[C]`.
4. Trango already offers a per-request signed attestation and avoids US-headquartered providers `[S: SRC-11]`. MapleRoute cannot match the second point because it routes to AWS and Azure.
5. At the assumed rates the stop rule in the brief fires 62.8% of the time even when every assumption is true (section 9), and cold outreach alone cannot reach break-even from a pool of a few hundred vendors (section 8).

What the 90 days must produce: at least 3 real security questionnaires, each AI-residency clause coded into the requirement classes of [section 4.4](#44-which-requirement-is-unmet), and at least 1 paid hand-run pilot. Build only if a class the customer's own cloud cannot satisfy shows up repeatedly **and** one economic condition of section 9.3 is met.

## 2. Who pays, who uses, what is billed

| Item | Definition |
|---|---|
| Launch market | BC and Ontario SaaS vendors selling AI features to municipalities and health organisations `[C]`. Founder in Vancouver `[C]`. |
| Buyer and budget owner | CTO or head of engineering of a 5–100 person vendor `[C]`. Whether CAD 500 sits inside that person's discretionary limit is unknown `[A]`. |
| Sign-off | Privacy officer or compliance lead `[C]`. |
| Daily user | The vendor's engineer who integrates the endpoint and reads rejections; the privacy lead who reads the monthly report. |
| The buyer's own customer | A municipality, health authority, school board, law firm, credit union or Quebec enterprise `[C]` whose questionnaire or contract asks where AI prompts are processed. Not a MapleRoute user. |
| **One paying account** `[P]` | One vendor legal entity (one tenant) that has paid at least one monthly subscription invoice after its pilot. A vendor in its 30-day pilot is a "paid pilot", not yet a paying account. |
| **One billable unit** `[P]` | One request accepted and forwarded to a provider. Rejected requests are not billed. Plans include 200K / 1M / 5M requests a month; extra requests cost CAD 10 per 100K `[C]`. Model tokens are paid by the customer to its own cloud account `[C]`. |

## 3. Launch market, problem, workaround

- **Problem `[C]`.** Vendors selling to health, legal, municipal and Quebec customers are asked to show that prompts and outputs stay in Canada. Regional model availability is confusing, and small teams have nobody to configure, monitor and document it.
- **Frequency `[C]`.** At each AI feature launch, each public-sector or enterprise security review, and whenever a provider changes regional availability.
- **Modelled benefit `[C]`, an assumption.** 25 engineer hours of setup and documentation at CAD 110 = CAD 2,750 once, plus 4 hours a month of monitoring = CAD 440 a month; one unblocked public-sector deal a year at an assumed CAD 30,000 would dominate. Nothing measured.
- **Current workaround `[C]`.** Configure Azure OpenAI Canada or Bedrock Canada directly and hope the right profile was chosen; self-host LiteLLM; avoid LLM features for sensitive customers; answer questionnaires by hand.
- **Legal driver.** For BC public bodies: "A public body may disclose personal information outside of Canada only if the disclosure is in accordance with the regulations" (FOIPPA s. 33.1) `[S: SRC-16]`. For Quebec: an assessment before personal information is communicated outside Quebec `[C]`, unverified; the statute could not be opened today (SRC-17 blocked). Canada has no federal AI statute in force `[C]`, so demand comes from procurement terms and provincial privacy law.
- **Quebec precision.** The Quebec rule concerns leaving Quebec, not leaving Canada `[C]`. A `ca.` Bedrock profile can route to Calgary `[S: SRC-02]`, and an Azure Standard deployment "might be processed between regions within that geography" `[S: SRC-06]`. "Canada-only" therefore does not mean "Quebec-only", and no message may imply it.

## 4. Competitor gap, supporting evidence, counterargument

### 4.1 What keeps inference in Canada today (read 2026-11-10)

"Stated" below means the provider's page says so. None of it is proof.

**AWS Bedrock `[S: SRC-01, SRC-02, SRC-03, SRC-04]`.** The page defines In-Region as processed "entirely within the single AWS Region you specify", Geo as routed "to a Region within a defined geography (US, CA, EU, APAC, JP, AU, IN)", and Global as any commercial Region.

| Group | Models (source Region `ca-central-1`) | Destination Regions stated | Eligible |
|---|---|---|---|
| In-Region | Titan Text Embeddings V2, Titan Multimodal Embeddings G1, Amazon Rerank, Claude 3 Haiku, Cohere Embed English, Embed Multilingual, Rerank 3.5, Llama 3 70B Instruct, Llama 3 8B Instruct, Mistral Large, Mixtral 8x7B Instruct, Mistral 7B Instruct (12; Claude 3 Sonnet shows end-of-life 2026-07-30 and is excluded) | `ca-central-1` | Yes |
| Geo with a `ca.` profile | Claude Haiku 5.5 (`ca.anthropic.claude-haiku-5-5`), Nova Lite (`ca.amazon.nova-lite-v1:0`) | `ca-central-1`, `ca-west-1` | Yes |
| Geo with only a `us.` profile | 29 models, including Claude Sonnet 5.5, Opus 5.5, Fable 5.2, Mythos 5.2, GPT-6.1 Sol, GPT-6 Sol, Nova 2 Lite, Grok 4.7, Kimi K3 | Source Region plus `us-east-1`, `us-east-2`, `us-west-2` | **No** |
| Global | Any `global.` profile | Any commercial Region | **No** |

AWS warns: "Don't rely on the geographic prefix in an inference profile ID alone", and tells customers with residency needs to call `GetInferenceProfile` from each source Region `[S: SRC-03]`. AWS also labels the `ca.` profiles as having limited model selection `[S: SRC-02]`. CloudTrail records cross-Region requests in the source Region with `additionalEventData.inferenceRegion` `[S: SRC-04]`.

**Azure (Foundry Models) `[S: SRC-06, SRC-07, SRC-08]`.** Global types "may be processed in any Azure region". Data Zone types exist for US, EU and APAC only; there is no Canada data zone. Standard and Regional Provisioned are processed "within the customer-specified Azure geography and might be processed between regions within that geography".

| Deployment type | `canadacentral` | `canadaeast` | Eligible |
|---|---|---|---|
| Standard (pay per token) | none listed | gpt-4.1-mini (2025-04-14), gpt-4o (2024-11-20), text-embedding-3-large, text-embedding-3-small, text-embedding-ada-002 | Yes |
| Regional Provisioned (reserved capacity) | gpt-4.1, gpt-4o (2024-05-13), gpt-4o-mini, gpt-5.2 | gpt-4o (3 versions), gpt-4o-mini, gpt-5, gpt-5-mini, gpt-5.1, gpt-5.2, o3-mini | Yes |
| Global Standard, Global Provisioned, Global Batch | 45 model versions incl. the GPT-6 family | 43 model versions | **No** |
| Data Zone (any) | not offered | not offered | n/a |

Azure Policy can deny a deployment type by `sku.name` `[S: SRC-06]`.

**Google Vertex AI, Montréal `[S: SRC-09, SRC-10]`.** The locations page, re-opened after review on 2026-11-10, marks 10 Google models as supported at `northamerica-northeast1` (Gemini 3.8 Flash, 3.5 Flash, 2.5 Pro, 2.5 Flash, Virtual Try-On, three embedding models and two text-to-speech models; the author's first reading counted 9) and no partner model (no Claude). It also says "Endpoints don't guarantee data residency or in-region ML processing". The data-residency page lists a Canada processing commitment for 7 rows (Gemini 3.5 Flash, 2.5 Flash, 2.5 Pro and two text-embedding models). Vertex is in the free map and not routed in the MVP `[P]`.

**Departures from the brief, recorded.**

| Brief said | Read today | Effect |
|---|---|---|
| Nova Lite is In-Region in `ca-central-1` | In-Region not supported; Geo supported through a `ca.` profile `[S: SRC-01, SRC-02]` | Still eligible, by a different route |
| Current Claude models in Canada are "Geo and Global cross-region only" | True, and for all but Claude Haiku 5.5 the Geo profile is the US one `[S: SRC-02]` | The brief's cold email ("the wrong one leaves the country") understates it: for most there is no right one |
| Cloudflare's pricing page "states no region control" | The page is silent on region and residency `[S: SRC-14]` | Reworded: "does not mention" |
| USP "prove every AI request stayed in Canada" | No party can prove this from outside the provider (section 4.3) | Replaced `[P]`: "allow only Canada-listed routes and show what each party reported" |
| Objection reply "You can fail open to your own direct Canadian deployment" | Conflicts with fail-closed if read as gateway behaviour | Reworded in section 12.7: a customer-side break-glass path, outside the report |

### 4.2 Competitors

| Alternative | What its own page says (2026-11-10) | Gap for this buyer |
|---|---|---|
| Azure or Bedrock used directly | Pay per token; native deny controls exist `[S: SRC-04, SRC-06]` | "This is the real alternative" `[C]`. Needs someone to choose correctly, watch for changes and write the answers |
| Sovereign AI Gateway (Trango Compute Inc., Ontario) | OpenAI-compatible; Llama 3.1 70B in an Ontario colocation facility; "Ed25519-signed attestation document" per request; signed deletion receipts; content "not retained after response delivery under standard configuration"; "Custom model deployment (on request)"; a white-label programme for companies that build software for healthcare, legal or municipal clients, which is MapleRoute's own customer profile; pricing by quote; no certification listed; subprocessors "available for review" but not named `[S: SRC-11]` | One open-weight model named; other models only on request; no hyperscaler frontier model. Its attestation is the vendor's own signed statement. It argues AWS and Azure Canada are exposed to US disclosure orders, which MapleRoute cannot answer |
| Portkey | Production USD 49/month, 100K logs, USD 9 per extra 100K; "Not recommended for organizations requiring custom security controls or data residency guarantees"; Enterprise offers private cloud `[S: SRC-12]` | Residency is an enterprise conversation |
| LiteLLM | Open source free and self-hosted; SSO, audit logs and RBAC in Enterprise by quote; page does not mention residency `[S: SRC-13]` | Customer runs it, monitors it and writes the evidence `[C]` |
| Cloudflare AI Gateway | Core features free; page does not mention region or residency `[S: SRC-14]` | No Canada control described on that page; other Cloudflare products not checked |

**Like-for-like price, monthly, CAD, 200K requests.** MapleRoute Starter CAD 149 `[C]`. Portkey Production USD 49 + USD 9 = USD 58 `[S: SRC-12]` × 1.38 = CAD 80.04 `[D]` (USD→CAD at the chat's scenario rate of 1.38 `[C]`: an undated assumption, not a sourced rate). Cloudflare CAD 0. LiteLLM CAD 0 plus the customer's hosting. Direct cloud CAD 0. Trango: not public. MapleRoute is the most expensive listed option and must justify the difference with evidence work, not proxying `[C]`.

**Vendor-advertised versus measured.** Everything above is advertised. No measured customer outcome exists for any option, including MapleRoute.

### 4.3 Evidence grades

Every claim in a MapleRoute report carries one grade `[P]`. The word "proof" is not used.

| Grade | Name | Meaning |
|---|---|---|
| EG-1 | Observed by MapleRoute | What the gateway itself did: host called, model or profile ID sent, allow-list version, decision, time |
| EG-2 | Provider-reported, per request | A field the provider recorded for that request, read from the customer's account (Bedrock CloudTrail `inferenceRegion`) |
| EG-3 | Provider-reported configuration | An API answer about configuration at a point in time (`GetInferenceProfile` destinations; Azure `sku.name` and location; MapleRoute's own database, backup and bucket settings) |
| EG-4 | Provider statement | Dated documentation or contract text |
| EG-5 | Not evidenced | Nobody outside the provider can show it |

| Topic | What MapleRoute can give | What it cannot give |
|---|---|---|
| Inference location | EG-1 route used; EG-3 destination set at last verification; EG-2 region per request on Bedrock cross-Region routes when the customer grants CloudTrail read; EG-4 provider text | Independent confirmation of where computation ran (EG-5). Any per-request region for Azure (none found today). Whether In-Region Bedrock calls carry `inferenceRegion` (not verified). Movement between Canada Central and Canada East inside Azure. Requests that bypass the gateway. **Azure residual window:** the gateway calls a deployment by a name the customer controls; its type is read every 15 minutes, not per request. A deployment re-created as Global Standard under the same name is unobserved until the next successful read: at most 15 minutes while checks succeed, and up to 60 minutes (the validity of the last matching check) when checks fail or run late. Each Azure line in the report states the longest time requests were served since a matching read and is never worded as continuous ([TRD.md](TRD.md#residual-window-on-azure)) |
| Request and response logs | EG-1 that the gateway stores metadata only, backed by a canary test; EG-3 region of its log store; EG-3 state and destination of the customer's own invocation or diagnostic logging, read by the verifier (MH-15) | Provider abuse-monitoring storage beyond EG-4. Azure states prompts may be stored for human review in the resource's geography and commits to reviewer location only for the EEA `[S: SRC-08]`. AWS states some models' traffic is retained up to 30 days in the destination Region `[S: SRC-05]` |
| Backups | EG-3 MapleRoute database backup region, retention and absence of cross-region copy | Provider-internal redundancy (EG-4 only) |
| Storage | EG-3 location of MapleRoute database, object store, key store and logs. No prompt or response content is stored | Memory contents on provider hosts (EG-5) |
| Subprocessors | A register with role, data seen, country of the legal entity and data location (EG-3 or EG-4 per row) | Sub-subprocessors. Foreign legal reach over a Canada-located, foreign-owned provider |

**The founder's VPS.** The chat said the product suits the founder's VPS `[C]`. Its provider and data-centre location are **not in the brief: unknown**. If any component that handles prompts, responses, provider credentials or request logs runs on a host whose location is unknown or outside Canada, the residency claim is false and MapleRoute must not make it. `[P]` The VPS is excluded from the data path; the data plane runs in AWS `ca-central-1` `[C]`. The VPS may host the public website only after task T-0.6.2 records provider, legal entity, data-centre city and evidence, and it appears in the subprocessor register either way.

**Provider credentials.** No application path shows a credential to anyone. The founder also administers the AWS account and its key policy, so administrator access to stored Azure secrets is possible; it is logged, not prevented ([TRD.md](TRD.md#credential-custody-mh-05-ad-06)). Buyers are told this.

**Draft subprocessor register `[P]`.** First version; nothing below has been read from a provider API or contract yet, so every location is "planned" or "not evidenced". The customer's own AWS and Azure accounts are the customer's processors, not MapleRoute's subprocessors.

| Party | Role | Data seen | Legal entity's country | Data location | Grade today |
|---|---|---|---|---|---|
| Amazon Web Services | Compute, database, backups, object store, keys, logs, alert email and paging | Request metadata, encrypted Azure secrets, account data. Prompts in memory only | United States parent | `ca-central-1` planned | Not evidenced until built; EG-3 after |
| Stripe | Billing | Billing contact, plan, monthly totals | United States | Not evidenced | EG-4 at best |
| Microsoft (Entra ID) and Google | Console sign-in, chosen by each customer | Name, email, subject identifier | United States | Not evidenced | EG-4 at best |
| GitHub | Source code, build and deploy pipeline | No customer data; holds deploy rights to production | United States | Not evidenced | EG-4 at best |
| Domain registrar and DNS host | Name resolution | Host names only | Unknown: the founder's existing domain `[C]` | Not evidenced | Not evidenced |
| Founder's VPS host | Public website at most | None if excluded as planned | Unknown | Unknown | Not evidenced |
| Uptime probe | Calls the health endpoint from outside | None | To be chosen | n/a | — |
| Contact tool, mail and spreadsheet used in phase 0 | Sales | Prospects' business contact details; pilot questionnaires and configuration records | To be recorded in T-0.4.3 before any pilot | To be recorded | Not evidenced |

### 4.4 Which requirement is unmet

Desk research cannot answer the decisive question. It can only set up the test. Each AI-residency clause in a collected questionnaire is coded into one class `[P]`:

| Class | Requirement as a buyer would write it | Existing cloud controls | Trango | MapleRoute |
|---|---|---|---|---|
| RQ-A | AI prompts are processed only in Canada | Met for the eligible set in 4.1, enforceable natively | Met for one model | Met for the eligible set; adds nothing but convenience |
| RQ-B | A named frontier model, Canada-only | Not met for most (4.1) | Not met | **Not met.** Request is rejected |
| RQ-C | Per-request record of processing location | Bedrock: CloudTrail field (EG-2). Azure: none found | Signed attestation by the vendor | Collates EG-1 to EG-3; cannot exceed them |
| RQ-D | A current, dated answer covering inference, logs, backups, storage and subprocessors, kept correct as providers change | Not packaged | For its own stack only | **Candidate gap.** The product hypothesis |
| RQ-E | No US-headquartered provider in the path | Not met | Claimed met | **Not met.** Disqualifies the prospect |
| RQ-F | Data stays in Quebec | In-Region `ca-central-1` only `[A]` (Montréal area `[C]`) | Not met (Ontario) | Not offered in MVP |

**Hypothesis under test:** buyers ask RQ-C and RQ-D often enough, and vendors find them hard enough, to pay CAD 149–999 a month. **Counter-hypothesis (the chat's stop rule):** most clauses are RQ-A and vendors answer them with cloud settings.

### 4.5 Strongest evidence and strongest counterargument

- **For.** The availability confusion is verified at the provider's own pages (4.1). Portkey's page says its self-serve plan is not for residency `[S: SRC-12]`.
- **Against.** "Hyperscalers provide the building blocks, so the gap is convenience and proof, not capability" `[C]`. Add today's reading: the product blocks the models buyers most want, and a proxy adds a subprocessor and a request-path dependency to a security review that is trying to remove them. The failure case in the brief is "a one-time cloud configuration and a paragraph in their security page" `[C]`.

## 5. Offer, channel, pilot

| Item | Value |
|---|---|
| Free step | A map of which models are processed in Canada `[C]`, then a 14-day free developer key `[C]` (the key exists only after the gateway does) |
| Paid pilot | CAD 500 for 30 days: gateway on one product plus the evidence pack filled in for one live customer questionnaire `[C]` |
| Tiers | CAD 149 / 399 / 999 a month; 15% annual discount `[C]` |
| Primary channel | Direct outreach to CTOs of Canadian govtech, healthtech and legaltech vendors, led by the free map `[C]` |
| Backup channel | Referrals from privacy lawyers and fractional privacy officers; 10% of first-year revenue `[C]` |
| Prospect sources | BC Tech Association, Council of Canadian Innovators, Digital Health Canada `[C]`; also procurement supplier lists, MaRS and Communitech directories, cloud partner directories `[C]` |
| Sample inputs | The questionnaire text, the list of models and deployments, read-only access to cloud configuration. No prompts and no end-user personal data |
| Sales cycle | 30 days `[C]` |
| Stop rule | Section 9 |

**How a paid pilot is delivered before software exists `[P]`.** The founder (a) reads the customer's Bedrock and Azure configuration through a read-only role or a screen share and records each profile and deployment as eligible or not; (b) hands over a provider-side policy template (IAM policy, optional service control policy, Azure Policy) that makes the provider refuse non-Canadian routes; (c) fills the evidence pack by hand for one questionnaire, each answer carrying its grade. No MapleRoute proxy is in the path. This departs from "gateway on one product" `[C]`; the pilot agreement says which form is delivered. A buyer who insists on the hosted gateway waits for milestone 7.1 in [execution-plan.md](execution-plan.md#phase-7--pilot-on-the-gateway-release-and-operations). If the hand-run form satisfies buyers, that is evidence the proxy is unnecessary, and it counts toward the stop rule.

**Pilot terms `[P]`.**

| Term | Value |
|---|---|
| Buys | 30 days from the day access is granted; one product, one cloud account per provider; one questionnaire's AI-residency items |
| Paid | CAD 500 plus applicable tax, invoiced at signature, due before day 1. Founder's GST registration status: missing input |
| Signs | CTO or head of engineering; privacy lead countersigns the data-handling page |
| Supplies | Customer: questionnaire, model list, read-only access within 5 business days (the clock pauses otherwise) |
| Success, measured by MapleRoute's dated deliverables | S1: configuration record covering every in-scope profile and deployment, by day 10. S2: evidence pack answering every AI-residency item, each with a grade, by day 20. S3 (gateway form only): zero requests forwarded on a route outside the allow-list, and zero requests inside a window in which the customer's deployment or policy was changed. The agreement states the Azure limit: configuration is re-read every 15 minutes, not per request, so a change can go unobserved for at most 15 minutes while checks succeed, and up to 60 minutes (the validity of the last matching check) when checks fail or run late. S3 is read from MapleRoute's log; the customer's independent check is its own cloud log, which the pack tells it how to query |
| Refund | Full refund if S1 or S2 is late or S3 fails. No refund because the buyer's own customer rejects an answer; that outcome is recorded as metric M-3 in [PRD.md](PRD.md#success-metrics) |
| Conversion | Review call on day 25; on day 30 the vendor chooses a published tier, billed monthly by card, or stops |

The brief also carries a "launch price" of CAD 249 and a week-4 gate of "2 customers at CAD 249 or more" `[C]`. No tier costs 249. What that price is: not decided in chat. `[P]` Pilots convert to a published tier only.

## 6. Reconciling tier prices, pilot price and assumed revenue per account

- Assumed revenue per account: CAD 320 a month `[C]`, equal to no tier.
- A mix that yields it `[D]`: 44% Starter, 51% Pro, 5% Business → 0.44 × 149 + 0.51 × 399 + 0.05 × 999 = 65.56 + 203.49 + 49.95 = **319.00**. With no Business accounts: 31.6% Starter, 68.4% Pro → 47.08 + 272.92 = 320.00. Either way more than half of accounts must buy Pro. Unsupported `[A]`.
- The cost notes assume 500K requests per account `[C]`. That exceeds Starter's 200K. Such an account pays Starter plus 3 × CAD 10 = CAD 179, or Pro at CAD 399 `[D]`. The 320 figure sits between them and matches neither.
- Annual billing at 15% off `[C]` would lower all of the above; the model ignores it.
- Pilot: CAD 500 once = 1.56 months of assumed revenue `[D]`. Net of card fees: 500 − (0.029 × 500 + 0.30) = 485.20 `[D]`, fee rate `[S: SRC-18]`.

## 7. Unit economics

All in CAD per month unless stated. No currency conversion is used in this section.

### 7.1 Inputs

| Input | Base `[C]` | Downside `[A]` |
|---|---|---|
| Revenue per account | 320 | 199 (80% Starter, 20% Pro: 119.20 + 79.80) |
| Variable cost per account | hosting 14, storage 2, support 55, other 12, payment 2.9% + 0.30 = 9.58 → **92.58** | payment = 6.07 → **89.07** |
| Monthly fixed cost excluding founder | 2,200 | 2,200 |
| Founder compensation | 6,000 | 6,000 |
| Acquisition cost per converted paying account (CAC) | 1,400 | 4,166.67 `[D]` |
| Monthly churn | 3% | 5% |
| Reply / meeting / close rates | 6% / 40% / 18% | 4% / 40% / 18%, and half of pilots convert |
| Startup cost | Brief: 100 hours × CAD 100 = CAD 10,000 of founder time `[C]`. Author's estimate: 271–408 hours × CAD 100 = **CAD 27,100–40,800** `[D]`. Cash: CAD 2,500 roadmap budget `[C]` and CAD 1,800 go-to-market budget `[C]`; the brief does not say whether the first contains the second | same |

**CAC has one definition here: cash spent on acquisition divided by converted paying accounts.** Founder time is carried by the CAD 6,000 line, not added again. Check `[D]`: CAD 1,800 budget `[C]` ÷ 1.296 accounts (section 8) = 1,388.89, which the model rounds to 1,400. That match holds only if every paid pilot becomes a paying account. The brief's own weekly plan has 2 pilots and 1 conversion `[C]`; the downside uses that 50%.

The author's build estimate in [execution-plan.md](execution-plan.md#estimate-summary) is 271–408 hours, well above the brief's 100 `[C]`, which covers a proxy only.

### 7.2 Results

| Measure | Base | Downside |
|---|---|---|
| Gross profit per account | 320 − 92.58 = **227.42** (71.1%) | 199 − 89.07 = **109.93** (55.2%) |
| Payback | 1,400 ÷ 227.42 = **6.16 months** | 4,166.67 ÷ 109.93 = **37.9 months** |
| Lifetime value | 227.42 ÷ 0.03 = **7,581** | 109.93 ÷ 0.05 = **2,199**, below CAC |
| Churn-replacement cost per account | 0.03 × 1,400 = **42.00** | 0.05 × 4,166.67 = **208.33** |
| Contribution after churn replacement | 227.42 − 42.00 = **185.42** | 109.93 − 208.33 = **−98.40** |
| Break-even accounts, no founder pay | 2,200 ÷ 185.42 = 11.86 → **12** | none: each account loses money |
| Break-even accounts, with founder pay | 8,200 ÷ 185.42 = 44.22 → **45** | none |

The base figures reproduce the chat's "Margin 71%. Break-even 12 (45)" `[C]`.

### 7.3 Cash required during the ramp

Model `[A]`: months M1–M3 are the validation cohort. Cash leaves as in section 12.8 (CAD 1,117, 466 and 217); pilot fees of 1.296 × 485.20 = 628.82 are booked in M3. Timeline shared with section 12.8: pilots start between day 45 and day 90, each runs 30 days, and an account's first full subscription month is M4, so the table shows no paying account before M4. Fixed cost starts in M4 with the first recurring accounts. The build needs 271–408 hours, so the gateway is ready about M6; accounts that convert before then are served by hand (a monthly configuration re-check and an updated pack) `[P]`. From M4 the founder keeps contacting 50 prospects a week = 216.67 a month → 0.936 new accounts a month from M5, each costing CAD 1,400. Accounts follow N(t) = 0.97 × N(t−1) + 0.936. The CAD 180 by which a pilot month exceeds a subscription month is ignored.

| Month | New | Paying accounts | Net, no founder pay | Cumulative, no founder pay | Cumulative, with founder pay |
|---|---|---|---|---|---|
| M1 | 0 | 0 | −1,117.00 | −1,117.00 | −7,117.00 |
| M2 | 0 | 0 | −466.00 | −1,583.00 | −13,583.00 |
| M3 | 0 | 0 | 411.82 | −1,171.18 | −19,171.18 |
| M4 | 0 | 1.296 | −1,905.26 | −3,076.44 | −27,076.44 |
| M5 | 0.936 | 2.193 | −3,011.66 | −6,088.10 | −36,088.10 |
| M6 | 0.936 | 3.063 | −2,813.75 | −8,901.85 | −44,901.85 |
| M9 | 0.936 | 5.520 | −2,254.95 | −16,214.16 | −70,214.16 |
| M12 | 0.936 | 7.763 | −1,744.95 | −21,948.66 | −93,948.66 |
| M18 | 0.936 | 11.678 | −854.67 | −29,223.32 | −137,223.32 |
| M24 | 0.936 | 14.939 | −113.09 | −31,689.94 | −175,689.94 |
| M25 | 0.936 | 15.426 | −2.14 | −31,692.07 | −181,692.07 |
| M26 | 0.936 | 15.900 | 105.48 | −31,586.59 | −187,586.59 |
| M36 | 0.936 | 19.917 | 1,019.17 | −25,277.24 | −241,277.24 |

- **Cash trough without founder pay: CAD 31,692 at M25** `[D]`. While acquisition continues the monthly net turns positive at 15.44 accounts, not 12, because each month also buys 0.936 new accounts.
- **With founder pay there is no trough inside 36 months:** the deficit is CAD 241,277 at M36 and still growing. Accounts converge on 0.936 ÷ 0.03 = 31.2 `[D]`, below the 45 needed. One founder at 50 contacts a week cannot reach break-even with founder pay at these rates, ever.
- **If the pool is exhausted.** Reaching M6 uses 300 + 3 × 216.67 = 950 contacts. If outreach stops after M6, accounts peak at 3.063 and decay; the deficit without founder pay is CAD 61,409 at M36 and never recovers.
- **Downside:** M3 pilot fees are 0.864 pilots × 485.20 = 419.21; 0.432 accounts in M4, 0.312 new a month, a ceiling of 6.24 accounts, deficit CAD 103,364 without founder pay at M36.

### 7.4 What would have to be true

Break-even with founder pay needs one of: revenue per account near CAD 999, a referral channel that removes the outreach ceiling, or churn near zero. None is evidenced.

## 8. Funnel recomputed from distinct reachable prospects

| Stage | Rate | Count per 300 contacts | Tag |
|---|---|---|---|
| Contacts | — | 300 | `[C]` |
| Replies | 6% | 18 | `[C]` |
| Meetings | 40% | 7.2 | `[C]` |
| Paid pilots = paying accounts in the base case | 18% | **1.296** | `[C]`, `[D]` |

This matches the chat's "300 → 18 → 7 demos → 1-2 customers" `[C]`. Per-contact probability: 0.06 × 0.40 × 0.18 = 0.00432 `[D]`.

**Distinct reachable prospects: unknown.** What the opened sources show: the BC Tech member directory has 49 pages with 20 entries on the first, about 970 listings across all sectors, unfiltered `[S: SRC-19]`; the Council of Canadian Innovators states "over 175 Canadian member companies" `[S: SRC-20]`; Digital Health Canada publishes no count on the pages opened `[S: SRC-21]`. The research record's judgement is "a few hundred vendors with hard residency clauses" `[C]`. No source counts vendors that ship an LLM feature **and** face a written residency clause. Task T-0.1.3 counts them.

**Pool against break-even `[D]`.** Twelve accounts need 12 ÷ 0.00432 = 2,778 contacts before churn; 45 need 10,417. A pool of 300–900 yields 1.3–3.9 accounts. **Cold outreach to this pool cannot reach break-even at the assumed rates.** The referral channel would have to carry most of the volume, and nothing supports that yet.

## 9. Stop rule checked against conversions, sample size and sales cycle

### 9.1 The rules as stated

- Chat `[C]`, translated: "When to stop: vendors say they can do it themselves with cloud settings."
- Research record `[C]`, verbatim: "Fewer than 2 paid pilots from 300 contacts, or interviews show most vendors are satisfied configuring Azure or Bedrock themselves."
- Offer `[C]`, translated: "A free map of Canadian model availability, then a CAD 500 pilot."

### 9.2 Checks

- With n = 300 and p = 0.00432, pilots are binomial with mean 1.296. P(0) = 0.99568^300 = 0.2729. P(1) = 300 × 0.00432 × 0.99568^299 = 0.3552. **P(fewer than 2) = 0.628** `[D]`. The pilot-count rule stops the project 62.8% of the time when every assumption is true. In the downside (p = 0.00288) it fires 78.6% of the time.
- For the rule to pass 80% of the time at the base rate, n must be 693 contacts `[D]`, about 14 weeks at 50 a week and probably more than the pool.
- The brief's week-1 gate (12 CTO interviews and 4 consultant interviews) and week-2 gate (2 paid pilots) `[C]` cannot be met in those weeks by a funnel whose cycle is 30 days and whose expected yield is 7.2 meetings from the whole cohort.
- The brief's gates, verbatim `[C]`: week 1, "At least 6 of 12 have faced a written residency question about AI in the past 12 months", with a task to "collect 5 real questionnaires"; week 2, "2 paid pilots". A cohort expected to yield 7.2 meetings cannot supply 12 interviews; section 9.3 keeps the question and lowers the counts.
- The chat's rule has no number. It needs one.

### 9.3 Proposed revision `[P]` — a change to the rules above, not a restatement

Decide on day 90, from the cohort of 300 contacts.

| Signal | Stop | Continue by hand, do not build | Build |
|---|---|---|---|
| Vendors saying own cloud settings suffice (the chat's rule) | More than half of meetings held, with at least 4 held | — | — |
| Vendors who faced a written AI-residency question in the past 12 months (the brief's week-1 question) | Fewer than half of meetings held, with at least 4 held | — | — |
| Questionnaires collected and coded (section 4.4) | Fewer than 3, or every clause is RQ-A, RQ-B or RQ-E | 3 or more, with RQ-C or RQ-D clauses in only 1 | RQ-C or RQ-D clauses in at least 2 of 3 |
| Paid pilots | 0 | 1 | 2 or more, or 1 plus the questionnaire Build signal |
| Economics (section 7.4) | — | None of the three conditions on the right | At least one: converted pilots choose tiers averaging CAD 399 or more; or at least 1 paid pilot came through a referral partner; or T-0.1.3 counts 2,778 or more qualified vendors |

Any Stop cell stops. **Build requires the Build cell in the questionnaire, pilot and economics rows together.** Otherwise the result is "Continue by hand": existing pilots are served without software and no build task starts.

**What "Build" means here.** Section 7.3 shows that break-even with founder pay is out of reach at the assumed rates. A Build decision therefore authorises only the P1 gateway for the customers already paying, as a second-stage test. It is not a finding that the business works. A further gate applies `[P]`: at 5 paying accounts or month 9, whichever comes first, stop new development unless revenue per account, referral share and churn observed by then put break-even with founder pay within 24 months when the section 7 arithmetic is re-run.

**False-stop rate of this rule, base rates true `[D]`.** Assumptions `[A]`: every paid pilot supplies its questionnaire; each other meeting yields one with probability y; the content-based Stop cells do not fire. The rule then stops when pilots are 0 or questionnaires are fewer than 3.

| Questionnaire yield y from non-pilot meetings | Expected questionnaires | Probability the rule stops wrongly |
|---|---|---|
| 1 in 1 | 7.2 | 28.0% |
| 1 in 2 (planning assumption `[A]`) | 4.25 | **35.7%** |
| 1 in 4 | 2.77 | 52.6% |

The revision lowers the false-stop rate from 62.8% to about 36% at the planning assumption; it does not remove it. Zero pilots alone occurs 27.3% of the time. The chance of meeting the pilot Build cell through 2 or more pilots is 37.2% `[D]`. No rule has good power at this sample size.

## 10. What buyer evidence would change the decision

- Toward build: two vendors forward questionnaires whose clauses demand per-request records or a maintained subprocessor and backup statement, and say nobody on their team can produce them.
- Toward stop: vendors paste a paragraph from their security page that their customers accepted; or their customers ask RQ-E.
- Toward a different product: buyers pay for the hand-run evidence pack and decline the proxy. That is a documentation service, not a gateway.
- Invalidation `[C]`: residency questions are rare or easily answered, or Bedrock and Azure offer all needed models fully in-region.

## 11. Missing inputs

| Missing | Needed for | Task |
|---|---|---|
| Founder VPS provider and location | Any residency statement that mentions it | T-0.6.2 |
| Count of distinct reachable prospects | Funnel, break-even feasibility | T-0.1.3 |
| What the CAD 249 "launch price" is | Tier reconciliation | T-0.5.4 |
| Breakdown of the CAD 2,200 fixed cost | Ramp start month | T-0.6.1 |
| Two budgets in the brief (CAD 1,800 for 30 days; CAD 2,500 roadmap) | Cash plan | T-0.6.1 |
| Text of Quebec's rule on communication outside Quebec | Any Quebec message | T-0.1.1 |
| Whether Azure returns a per-request region field; which Azure activity-log events and deployment timestamps a reader can see | RQ-C on Azure; the residual window | T-1.1.3 |
| Questionnaire yield per meeting | False-stop rate of the stop rule | T-0.4.2 |
| GST registration status | Pilot invoice | T-0.5.1 |

## 12. Go-to-market plan

One cohort: **300 contacts, 50 new first touches a week for 6 weeks, one follow-up each, 30-day cycle, decision on day 90.** The brief's 100 emails a week `[C]` is halved `[P]` because each address must be checked by hand (12.4). The funnel, hours, tasks and stop rule all use 300 and 50.

### 12.1 Ideal customer profile

- Canadian B2B SaaS vendor, 5–100 staff, adding LLM features, selling to municipalities, health authorities, school boards, law firms, credit unions or Quebec enterprises `[C]`.
- Qualifies `[C]`: ships or plans an LLM feature, sells to a buyer with a written Canadian residency requirement, has no platform engineer dedicated to it.
- Trigger `[C]`: an RFP with a residency clause; a privacy assessment request; a questionnaire asking where prompts are processed; discovery that a Bedrock profile routes outside Canada.
- Disqualified `[P]`: needs a model outside section 4.1's eligible set (RQ-B); its customer requires no US-headquartered provider (RQ-E); needs Quebec-only (RQ-F); has a platform team; will not put a third party in the request path.

### 12.2 Named roles

| Role | Person |
|---|---|
| Feels the pain | Engineer or CTO who answers the questionnaire |
| Signs and pays | CTO or head of engineering `[C]` |
| Can block | Privacy officer `[C]`; the vendor's own customer's security reviewer |
| Supplies sample data | CTO: questionnaire, model list, read-only cloud access |

### 12.3 Prospect list

Sources in section 5. Built by hand in a spreadsheet: company, sector, evidence of an LLM feature, evidence of public-sector or health customers, contact, where the address was published, date seen. A paid contact tool at about CAD 250 per 100 contacts `[C]` finds companies and roles only. Count: unknown (section 8); T-0.1.3 records it before sending starts.

### 12.4 Channel and sequence

**Outreach law, read at the source `[S: SRC-15]`.** Canada's anti-spam Act (S.C. 2010, c. 23) prohibits sending a commercial electronic message unless the recipient "has consented to receiving it, whether the consent is express or implied" and the message identifies the sender, gives contact information and "an unsubscribe mechanism" (s. 6(1)–(2)). Contact information must stay valid for 60 days (s. 6(3)). Consent is implied "only if" one of the cases in s. 10(9) applies. The two usable here: the recipient "has conspicuously published" the address without a no-solicitation statement and the message is relevant to their role (s. 10(9)(b)); or an existing business relationship, which includes an inquiry in the previous six months (s. 10(10)(e)). An address found by a tool is not conspicuous publication by the recipient. The unsubscribe mechanism must work at no cost by the same electronic means (s. 11(1)).

| Channel | Consent basis relied on | Rule |
|---|---|---|
| Email to an address on the company's own site or a speaker page | s. 10(9)(b) | URL and date recorded per contact; skipped if a no-solicitation statement appears |
| Reply to a map inquiry | s. 10(10)(e) | Within six months of the inquiry |
| LinkedIn message | Unclear; a message to an account is an electronic message | Not sent until counsel answers in T-0.1.1 |
| Introductions and events | Not electronic messages when in person | First channel for the founder's own network |

Every message, including follow-ups, carries sender name, business name, mailing address, a contact method and an unsubscribe line. No US or UAE recipients are in this cohort; CAN-SPAM and UAE rules must be checked before any are added. Sending is gated on T-0.1.1.

Sequence: first touch in weeks 1–6; one follow-up 5 business days later; then stop. Founder time: 6 minutes to verify, 4 to write, 2 to follow up per contact = 10 hours a week `[A]`.

### 12.5 Message

Synthetic examples. Names and addresses are invented.

> **Subject:** Where Harbourline's AI prompts are processed
>
> Hi Priya,
>
> I found your address on Harbourline's team page. When a municipal customer asks whether your AI features keep data in Canada, what do you send them?
>
> I read the AWS and Azure pages this week. On Bedrock, most current Claude models reached from the Canadian Regions use a US profile; two models have a Canada-only one. I keep a one-page map of what is processed in Canada and can send it, free.
>
> I also run a 30-day pilot for CAD 500: I check your cloud configuration against that map and fill in the AI-residency answers for one real questionnaire, marking what each answer rests on. You would send the questionnaire and give read-only access to the configuration.
>
> Sam Okafor, MapleRoute, 000 Example Street, Vancouver BC. Reply to this email or call 604-555-0100. To stop hearing from me, reply "unsubscribe".

> **Subject:** Re: Where Harbourline's AI prompts are processed
>
> Hi Priya, one follow-up and then I will stop. The map is attached to nothing; reply "map" and I will send it. The pilot stays CAD 500 for 30 days.
>
> Sam Okafor, MapleRoute, 000 Example Street, Vancouver BC. 604-555-0100. Reply "unsubscribe" to stop.

### 12.6 Pilot offer and conversion

As in section 5. The pilot ends on day 30 or when S1–S3 are judged, whichever is later. The step to a recurring account is one decision on the day-25 call: choose Starter, Pro or Business and enter a card, or stop.

### 12.7 Objections

| Objection | Honest answer |
|---|---|
| "We can configure Azure or Bedrock ourselves." `[C]` | You can, and for one model on one cloud you should. The pilot gives you the policy templates either way. What you would pay for afterwards is someone watching the provider pages and keeping your answers current. If that is not worth CAD 149 a month to you, do not buy |
| "Trango already signs an attestation per request." | It does, for a model on its own hardware, and it offers custom models on request and a white-label programme for vendors like you `[S: SRC-11]`. If your customer requires no US-headquartered provider, or an open-weight model is enough, choose Trango. Its page names no Azure or Bedrock model; if you need one, neither of us can give more than the cloud's own record |
| "Another hop adds latency and risk." `[C]` | True. The gateway runs in the same Canadian Region `[C]` and rejects instead of rerouting. One limit you should know: on Azure we re-read your deployment type every 15 minutes, not per request, so a change on your side can go unobserved for at most 15 minutes while checks succeed, and up to 60 minutes (the validity of the last matching check) when checks fail or run late. Your application may keep its own direct path to your own Canadian deployment as a break-glass; those requests are outside the report and appear as a gap |
| "You do not have SOC 2." `[C]` | Correct. No certification exists or is scheduled. Prompts are not stored, and the register lists every subprocessor |

### 12.8 First 30, 60 and 90 days

Expected values at the base rates. Hours `[A]`.

| | Day 30 | Day 60 | Day 90 |
|---|---|---|---|
| First touches sent (cumulative) | 200 | 300 | 300 |
| Replies | 9 (from the first 150) | 18 | 18 |
| Calls held | 2.4 (from the first 100) | 7.2 | 7.2 |
| Questionnaires in hand (y = 1 in 2) | 1.2 | 3.82 | 4.25 |
| Paid pilots started | 0 | 0.864 (from the first 200) | 1.296 |
| Pilots completed and subscribed (first full subscription month is M4, as in section 7.3) | 0 | 0 | 0.864 |
| Cash spent, cumulative | CAD 1,117 | CAD 1,583 | CAD 1,800 |
| Founder hours, cumulative | 79 | 136 | 155 |

Cash split `[A]` of the CAD 1,800 (the brief's 30-day budget `[C]`, spread over 90 days `[P]`; the CAD 2,500 roadmap budget `[C]` is not used here): contact tool 750, one hour of privacy counsel 400, cloud accounts and monitoring 650. Hours, equal to the low estimates of phase 0 in [execution-plan.md](execution-plan.md#phase-0--validation-and-go-to-market): outreach 10 a week for 6 weeks = 60; prospect count 3; map 12 to build plus 2 a week for 12 weeks; legal gate 3; replies 0.25 each; calls 1.5 each; questionnaire coding 3; pilot working environment record 2; grade catalogue and pack template 3; partners 4; hand-run pilot 17 each (agreement 2, configuration 4, evidence pack 10, review 1) × 1.296 = 22; decision 3; hosting record 1. Total 155.3, about 12 a week. The brief's 70 hours in 30 days `[C]` compares with 79 here.

Weekly targets: 50 verified first touches, 50 follow-ups, replies answered within one business day, map re-read every Monday.

### 12.9 GTM stop rule

The table in section 9.3. In addition, drop the **channel** (not the product) if fewer than 6 replies arrive from the first 200 contacts (expected 12), and switch the remaining effort to privacy consultants.

## 13. Sources and assumptions

All consulted 2026-11-10. "Open" means no login was needed.

| ID | Source and URL | Jurisdiction | Scope used | Access |
|---|---|---|---|---|
| SRC-01 | AWS, Bedrock model and Region compatibility — docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html | AWS, Canada Regions | 149 model tables; 48 with a Canada row | Open |
| SRC-02 | AWS, Bedrock model cards (46 opened) — docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html | same | Profile IDs, source and destination Regions | Open |
| SRC-03 | AWS, Supported Regions and models for inference profiles — …/userguide/inference-profiles-support.html | same | `GetInferenceProfile`; prefix warning | Open |
| SRC-04 | AWS, cross-Region inference and geographic cross-Region inference — …/userguide/cross-region-inference.html, …/geographic-cross-region-inference.html | same | CloudTrail field; policy controls | Open |
| SRC-05 | AWS, Bedrock abuse detection and data protection — …/userguide/abuse-detection.html, …/data-protection.html | same | Retention statements | Open |
| SRC-06 | Microsoft, Deployment types in Foundry Models (dated 2026-08-06) — learn.microsoft.com/azure/foundry/foundry-models/concepts/deployment-types | Azure | Processing location by type; Azure Policy | Open |
| SRC-07 | Microsoft, Region availability for Foundry Models sold by Azure (dated 2026-09-03) — …/concepts/models-sold-directly-by-azure-region-availability | Azure, Canada regions | Models by deployment type | Open |
| SRC-08 | Microsoft, Data, privacy and security for Foundry Models sold by Azure (dated 2026-05-18) — learn.microsoft.com/azure/foundry/responsible-ai/openai/data-privacy | Azure | Storage, abuse monitoring | Open |
| SRC-09 | Google, Vertex AI locations (updated 2026-11-10) — docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations | Google Cloud, Montréal | Endpoint availability | Open; table cells read from page markup; opened twice |
| SRC-10 | Google, Vertex AI data residency — …/docs/learn/data-residency | same | Processing commitments | Open |
| SRC-11 | Trango Compute, Sovereign AI Gateway — sovereign-ai-gateway-site.pages.dev | Ontario | Offer, attestation, pricing | Open |
| SRC-12 | Portkey pricing — portkey.ai/pricing | Global | Plans, residency note | Open |
| SRC-13 | LiteLLM pricing — litellm.ai/pricing | Global | Plans | Open |
| SRC-14 | Cloudflare AI Gateway pricing — developers.cloudflare.com/ai-gateway/reference/pricing | Global | Pricing; silence on region | Open |
| SRC-15 | An Act to promote the efficiency and adaptability of the Canadian economy… (S.C. 2010, c. 23), current to 2026-10-19 — laws-lois.justice.gc.ca/eng/acts/E-1.6/FullText.html | Canada | ss. 6, 10(9)–(10), 11(1)–(2). Regulations not read | Open |
| SRC-16 | Freedom of Information and Protection of Privacy Act (BC), Part 3 — bclaws.gov.bc.ca | British Columbia | s. 33.1 only; the regulation it refers to was not read | Open |
| SRC-17 | Act respecting the protection of personal information in the private sector (Quebec), s. 17 — legisquebec.gouv.qc.ca | Quebec | **Blocked** (HTTP 403 and 502). The brief's law-firm summary stays unverified | Blocked |
| SRC-18 | Stripe pricing, Canada — stripe.com/en-ca/pricing | Canada | 2.9% + CAD 0.30 domestic cards | Open |
| SRC-19 | BC Tech Association member directory — wearebctech.com/members/member-directory | BC | Page count; entries per page | Open; total is an estimate |
| SRC-20 | Council of Canadian Innovators — canadianinnovators.org | Canada | Member count statement | Open; member list page returned 404 |
| SRC-21 | Digital Health Canada — digitalhealthcanada.com | Canada | No member count found | Open; corporate member page returned 404 |
| SRC-22 | OWASP ASVS 5.0.0, chapters V2, V3, V4, V6, V7, V8, V10, V11–V14, V16 — github.com/OWASP/ASVS, tag v5.0.0 | — | Requirement text cited in TRD | Open |
| SRC-23 | W3C, WCAG 2.2 — w3.org/TR/WCAG22 | — | Criteria cited in design.md | Open |

Not reopened: the Microsoft Q&A answer in the brief (secondary `[C]`); arc42 and Spec Kit (structure taken from the author guide). Unresolved assumptions are listed in section 11 and in [verification-report-fixing.md](verification-report-fixing.md#outstanding-items).
