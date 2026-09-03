# Step A of the extraction protocol: permissive, over-inclusive candidate generation.
# The LLM no longer judges whether a candidate is a "true" entity or an actor -- that decision is
# delegated to a downstream deterministic layer (dependency parsing / WordNet lexnames). This step
# has one job only: do not miss anything. Precision on WHICH candidates to include is not this
# step's responsibility; recall is.
#
# However, formatting discipline IS this step's responsibility, independently of that judgment.
# Observed failure mode this version corrects: candidate names and states degenerating into full
# clauses copied from the source text (e.g. a "state" of {"description of the condition under
# which X is considered part of an event"} instead of a short label) -- this breaks every
# downstream step (symbolic validation, evidence citation, graph construction), regardless of
# whether the candidate itself is entity-worthy. Format correctness and inclusion judgment are
# two separate concerns, and this version enforces the first strictly while staying permissive on
# the second.
#
# Revision 3 -- mutual-exclusivity detection is DECOUPLED from this step into its own,
# separate LLM call (EXCLUSIVE_GROUPS_PROMPT, below). Rationale, not specific to any one model or
# domain: generous enumeration ("find every state, don't miss anything") and relational judgment
# ("do these two specific states rule each other out?") are two different reasoning tasks, and
# asking for both under one dominant instruction ("be exhaustive") empirically starved the second
# one -- across two full test runs on real backbones, 5 of 7 models never populated
# exclusive_groups even when the two complementary states were sitting right there in their own
# output, while the one model that did use the field initially over-applied it to plain sequential
# stages. Splitting the task lets each pass carry the instruction that actually matches its job:
# Step A stays recall-oriented (never mind exclusivity), the new pass is precision-oriented and
# grounded by a mandatory verbatim quote per claimed pair. This also removes, by construction, a
# failure mode the original single-pass design could produce: a model asserting a pair against a
# complementary state it never added to its own "states" list -- since the exclusivity pass in
# state_space_node_v3.py now only ever sees, and may only choose from, states Step A already
# committed to and Step B already validated.
#
# A candidate's value from THIS step is therefore {"states": [...], "concurrent_with": [...]}
# only. "exclusive_groups" is not part of Step A's output schema anymore; it is populated later,
# by generate_exclusive_groups() in state_space_node_v3.py, using EXCLUSIVE_GROUPS_PROMPT below.



_CANDIDATE_DEFINITION = """A candidate is a short noun phrase (1 to 4 words) that names something in the process which could plausibly be described as passing through different conditions over time.

Do not decide whether a candidate is a "real" entity, an actor, or a role -- that judgment is made separately, after this step. Your only responsibility here is completeness: include every candidate that is associated with a condition, an action taken on it, or an outcome in the text, even if you are unsure it will ultimately qualify.

When in doubt about whether to INCLUDE a candidate, include it. Formatting correctness, below, is never optional -- it applies even to candidates you are unsure about."""

_FORMAT_RULES = """Formatting rules for every candidate name and every state -- these apply without exception:
- A candidate name is a short noun phrase, 1 to 4 words, never a sentence or a clause. "childcare facility" is a valid candidate name. "taking a child to or collecting them from a childcare facility" is NOT a valid candidate name -- that is a clause describing an action, not a thing.
- A state is a short condition label, 1 to 3 words, written as a past participle or an adjective (e.g. "submitted", "confirmed", "active", "under_review"). A state is NEVER a full sentence, a clause, a paraphrase of a rule, or a copy of a condition from the text.
- WRONG example: {{"childcare_facility": ["taking a child to or collecting them from is considered part of the work accident conditions"]}}
- RIGHT example: {{"childcare_facility": {{"states": ["visited"]}}}}
- If you cannot express a condition as a short label without copying a clause or inventing unstated content, do NOT include it as a state -- omit it rather than write a sentence.
- Never start a candidate name or a state with a verb in -ing form, with "the fact that", "it is considered", or any other clause opener.
- Use lowercase. Use snake_case for multi-word labels (e.g. "information_collected", "childcare_facility").

Each candidate maps to an OBJECT, never a bare list, with up to two keys:
- "states" (required): the list of condition labels, exactly as described above.
- "concurrent_with" (optional): a list of OTHER candidate names (not states) that the text explicitly describes as happening at the same time as this one -- only when the text uses an explicit marker such as "while", "in the meantime", "simultaneously", "in parallel". Never infer concurrency from silence or from mere proximity in the text. Omit this key entirely when there is no explicit marker.

Do NOT decide which of a candidate's states are mutually exclusive alternatives to each other -- that judgment belongs to a separate, later pass and is out of scope here. Simply list every state you find; a later step will look at your list and decide on its own which states, if any, rule each other out.

When the text describes an action repeated over a list or set of items ("for each item", "every part on the list", "one by one"), do not create one state per item and do not invent item-indexed states -- represent the aggregate outcome as a single completion state (e.g. "complete", "fully_processed") on a candidate that stands for the whole batch/list/set as a unit, kept separate from the per-item action itself."""

_SCHEMA_EXAMPLE = """Pattern: iteration completion and explicit concurrency (not exclusivity -- that is handled separately, later):

Text: "A compliance team verifies an applicant's documents while the application itself is still being evaluated, in parallel. Once every required document has been verified, the compliance check is marked complete."

Output: {{"application": {{"states": ["under_evaluation"], "concurrent_with": ["compliance_check"]}}, "compliance_check": {{"states": ["in_progress", "complete"], "concurrent_with": ["application"]}}}}

Note: the repeated per-document verification ("every required document has been verified") is not modeled as one state per document -- it collapses into a single completion state on a container candidate that stands for the whole check. The phrase "while ... in parallel" is an explicit marker, so "application" and "compliance_check" cross-reference each other via concurrent_with; without such an explicit marker, concurrent_with must be omitted, not guessed. Neither candidate is given an "exclusive_groups" key -- deciding which states are mutually exclusive alternatives is not this step's job."""


STATE_SPACE_PROMPT_PERMISSIVE = """You are performing the first step of a two-step extraction pipeline: generous candidate generation. A separate, later step will filter your candidates -- do not filter them yourself.

{definition}

{format_rules}

Rules:
- Be over-inclusive on WHICH candidates you list. Do not omit a candidate because you are unsure it qualifies.
- Base every candidate and every state on something stated or clearly implied in the text -- do not invent content absent from the text.
- Output strict JSON only: {{{{"candidate_name": {{{{"states": ["state1", "state2", ...], "concurrent_with": ["other_candidate_name"]}}}}, ...}}}}
- No prose, no explanation, no markdown fences.

Text:
{{text}}
""".format(definition=_CANDIDATE_DEFINITION, format_rules=_FORMAT_RULES)


STATE_SPACE_PROMPT_PERMISSIVE_FEWSHOT = """You are performing the first step of a two-step extraction pipeline: generous candidate generation. A separate, later step will filter your candidates -- do not filter them yourself.

{definition}

{format_rules}

Rules:
- Be over-inclusive on WHICH candidates you list. Do not omit a candidate because you are unsure it qualifies.
- Base every candidate and every state on something stated or clearly implied in the text -- do not invent content absent from the text.
- Output strict JSON only: {{{{"candidate_name": {{{{"states": ["state1", "state2", ...], "concurrent_with": ["other_candidate_name"]}}}}, ...}}}}
- No prose, no explanation, no markdown fences.

Example 1:
Text: "A library manages book loans. When a member borrows a book, it becomes checked out. If it is returned on time, it becomes available again. If returned late, it is marked overdue before returning to available. If a book is lost, it becomes lost and is removed from the catalog. Members can reserve a book that is checked out; once returned, a reserved book becomes held for the requesting member before being checked out again."

Output: {{{{"book": {{{{"states": ["available", "checked_out", "overdue", "held", "lost"]}}}}}}}}

Note: only "book" is described with explicit condition changes in this text. "member" is not included -- the text never describes a condition change happening to a member. Every state above is a single short label, never a clause copied from the text -- for example the state is "checked_out", not "a member borrows the book and it becomes checked out".

Example 2 (iteration and explicit concurrency):
{schema_example}

Now extract candidates for the following text, following the same approach: generous inclusion, short labels only, grounded only in what the text states or clearly implies.

Text:
{{text}}
""".format(definition=_CANDIDATE_DEFINITION, format_rules=_FORMAT_RULES, schema_example=_SCHEMA_EXAMPLE)


STATE_SPACE_PROMPT_PERMISSIVE_TWOSHOT = """You are performing the first step of a two-step extraction pipeline: generous candidate generation. A separate, later step will filter your candidates -- do not filter them yourself.

{definition}

{format_rules}

Rules:
- Be over-inclusive on WHICH candidates you list. Do not omit a candidate because you are unsure it qualifies.
- Base every candidate and every state on something stated or clearly implied in the text -- do not invent content absent from the text.
- A text may require one candidate or several distinct candidates. Do not force everything into one, and do not split one lifecycle into unrelated fragments.
- Output strict JSON only: {{{{"candidate_name": {{{{"states": ["state1", "state2", ...], "concurrent_with": ["other_candidate_name"]}}}}, ...}}}}
- No prose, no explanation, no markdown fences.

Example 1 (single candidate):
Text: "A library manages book loans. When a member borrows a book, it becomes checked out. If it is returned on time, it becomes available again. If returned late, it is marked overdue before returning to available. If a book is lost, it becomes lost and is removed from the catalog. Members can reserve a book that is checked out; once returned, a reserved book becomes held for the requesting member before being checked out again."

Output: {{{{"book": {{{{"states": ["available", "checked_out", "overdue", "held", "lost"]}}}}}}}}

Note: "member" is not included -- the text never describes a condition change happening to a member. Every state is a single short label, never a clause.

Example 2 (two distinct candidates):
Text: "An online store processes customer orders. When a customer places an order, it becomes pending. The store confirms the order, making it confirmed. Once confirmed, a shipment is created for the order and starts as preparing. The shipment becomes shipped once it leaves the warehouse, and delivered once the customer receives it. If a shipment is lost in transit, it becomes lost. If the customer cancels before shipping, the order becomes cancelled and no shipment is created."

Output: {{{{"order": {{{{"states": ["pending", "confirmed", "cancelled"]}}}}, "shipment": {{{{"states": ["preparing", "shipped", "delivered", "lost"]}}}}}}}}

Note: "order" and "shipment" both have explicit condition changes described in the text, so both are included as separate candidates. "customer" and "store" are not. Again, every state is a short label, not a clause.

Example 3 (iteration and explicit concurrency):
{schema_example}

Now extract candidates for the following text, following the same approach.

Text:
{{text}}
""".format(definition=_CANDIDATE_DEFINITION, format_rules=_FORMAT_RULES, schema_example=_SCHEMA_EXAMPLE)


STATE_SPACE_PROMPT_PERMISSIVE_COT = """You are performing the first step of a two-step extraction pipeline: generous candidate generation. A separate, later step will filter your candidates -- do not filter them yourself.

{definition}

{format_rules}

{schema_example}

Work through the following steps explicitly before answering:

Step 1 -- List every noun phrase in the text, without exception.
Step 2 -- For each one, note whether the text describes any change, status, action taken on it, or outcome associated with it. If yes, or if you are unsure, keep it as a candidate.
Step 3 -- For each candidate kept, list the conditions it is described as passing through, or could plausibly pass through, based only on the text. Write each condition as a short label following the formatting rules above -- never as a clause or sentence. If you cannot compress a condition into a short label without inventing content, drop it rather than writing a sentence. While doing this, specifically check for two patterns and encode them using the schema fields above rather than dropping them: (a) an action repeated over a list or set of items -- encode as a single aggregate completion state, not one state per item; (b) an explicit textual marker of simultaneity ("while", "in the meantime", "simultaneously", "in parallel") -- encode as "concurrent_with" on both candidates involved. Do not attempt to judge which states are mutually exclusive alternatives -- that is a separate, later pass, not this one.
Step 4 -- Re-check every candidate name and every state against the formatting rules above. If any of them is a clause, a sentence, or starts with a gerund, rewrite it as a short label or remove it. Confirm every candidate's value is an object with a "states" key (never a bare list), and that "concurrent_with" is present only when the text actually supports it.

Do not attempt to judge whether a candidate is a "real" entity or an actor at this step -- that is done later, outside this task.

After Step 4, output the line "FINAL_ANSWER:" followed immediately by strict JSON only, no prose, no markdown fences:
{{{{"candidate_name": {{{{"states": ["state1", "state2", ...], "concurrent_with": ["other_candidate_name"]}}}}, ...}}}}

Text:
{{text}}
""".format(definition=_CANDIDATE_DEFINITION, format_rules=_FORMAT_RULES, schema_example=_SCHEMA_EXAMPLE)


# --- Second, decoupled LLM call: mutual-exclusivity detection only ---
#
# Deliberately separate from Step A above (see Revision 3 note at the top of this file). Input is
# the text plus the entity -> states mapping Step A/B already produced (after lexical ACTOR
# filtering, so this pass never has to reason about actors). Output is only the pairs it finds
# evidence for, each grounded by a mandatory verbatim quote -- never a bare boolean judgment, and
# never a state that was not already given to it. Domain- and model-agnostic: the definition,
# rules, and worked example below make no reference to any specific business domain or any
# specific text seen elsewhere in this project, and nothing here is tuned to any one model's
# known failure pattern -- the instructions describe the task and its evidentiary bar, not a
# workaround for a particular backbone.

_EXCLUSIVE_GROUPS_DEFINITION = """You will be given a source text and a list of entities, each with the states it was already found to pass through in that text. Your only task: for each entity, decide whether any two of ITS OWN states are described in the text as mutually exclusive alternatives for a single instance -- meaning the text presents them as a choice where one outcome rules out the other, not as two stages the same instance passes through one after another over time.

This is not a completeness task. Most entities have no exclusive states at all, and that is the expected, correct answer for most of them -- only report a pair when the text gives you a specific, quotable reason to."""

_EXCLUSIVE_GROUPS_RULES = """Rules, without exception:
- Only choose states that are already in the given list for that entity. Never introduce a new state name that is not already listed -- if the text implies a state that was not extracted, that is a gap in an earlier step, not something to invent here.
- Every reported pair MUST be accompanied by a "quote": a short, verbatim excerpt from the text (under 20 words) that is your evidence the two states are alternatives, not a sequence. If you cannot point to specific wording that presents them as alternatives, do not report the pair.
- The default is NO exclusive pair. Consecutive stages of a normal process ("submitted" then "confirmed" then "rated") are NOT exclusive, no matter how tempting it is to pair up states belonging to the same entity. Only mark a pair when the text poses them as a decision, a branch, or the two sides of a threshold or condition (e.g. approved vs. denied, above a cutoff vs. at or below it, accepted vs. rejected).
- If an entity has no such pair, omit it from your output entirely -- do not include it with an empty list.
- Output strict JSON only, no prose, no markdown fences: {{"exclusive_groups": [{{"entity": "entity_name", "states": ["stateA", "stateB"], "quote": "verbatim excerpt from the text"}}, ...]}}"""

_EXCLUSIVE_GROUPS_EXAMPLE = """Example:
Text: "A committee reviews grant proposals. After review, each proposal is either funded or rejected. A funded proposal then moves to the disbursement stage, where funds are transferred to the recipient."

Entities:
- "proposal": ["reviewed", "funded", "rejected", "disbursed"]

Output: {{"exclusive_groups": [{{"entity": "proposal", "states": ["funded", "rejected"], "quote": "each proposal is either funded or rejected"}}]}}

Note: "reviewed" and "disbursed" are NOT included in any pair -- they are stages a funded proposal passes through over time, not alternatives to anything. Only "funded"/"rejected" are reported, because the text explicitly poses them as an either/or outcome of review."""

EXCLUSIVE_GROUPS_PROMPT = """You are performing a narrow, second-pass task on a process description: identifying mutually exclusive states, separately from the earlier step that already extracted the states themselves. You are not asked to extract, rename, merge, or judge any state here -- only to decide, for the states you are given, which ones (if any) are alternatives to each other.

{definition}

{rules}

{example}

Entities and their already-extracted states:
{{entities}}

Text:
{{text}}
""".format(definition=_EXCLUSIVE_GROUPS_DEFINITION, rules=_EXCLUSIVE_GROUPS_RULES, example=_EXCLUSIVE_GROUPS_EXAMPLE)