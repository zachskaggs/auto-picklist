-- CardKingdom's own name/edition strings, snapshotted at batch creation so the
-- CSV export matches CK's sell importer regardless of later buylist refreshes.
ALTER TABLE batch_items ADD COLUMN ck_name TEXT;
ALTER TABLE batch_items ADD COLUMN ck_edition TEXT;
