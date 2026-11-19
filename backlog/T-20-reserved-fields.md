---
type: Task
title: 'Reserved custom fields the classifier never sets, changes or clears'
status: erledigt
id: T-20
milestone: M-1
tags: [felder, rechte]
created: '2026-11-19'
---
# T-20 — Reserved custom fields the classifier never sets, changes or clears

**Occasion (2026-11-19):** An installation files documents under a case or topic with a select field (one option
per case). Only a person sets it. `manual_fields` kept such a field away from the model, but not from every path of
the classifier: a split part (`erbe_verwerfen`) drops every value inherited from its source document, the case
included, and the warranty code writes its end field whatever the list says.

**Implementation:** new config key `reserved_fields` (names, case-insensitive), the field counterpart of
`reserved_tags`. A reserved field

- is not in the model's field list, so neither its name nor its options reach the prompt (select options would
  otherwise invite the model to pick one);
- keeps its value on every write-back, an empty assignment included — set, change and clear are all impossible;
- survives the split part: its value is taken from the document before the inherited values are dropped;
- switches the warranty feature off when it is one of the two warranty fields, since that code writes by itself;
- is left out of the panel's preview of model fields and is shown among the settings.

**Measured:** real runs of `main()` against a fake Paperless (select field with two options): the model's
proposal to set, change or clear the field never reaches the patch, on import and on the AI button; a split part
keeps the case and still sheds its other inherited values. Counter-checks without the reservation: the same answers
set, clear and drop the field, so the tests measure the reservation and not the harness. 8 of 8 mutants red,
`check.sh` green twice.
