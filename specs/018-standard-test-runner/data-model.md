# Data model
manifest.json: schema_version, run_id, created_at, input_root, config, code_hashes, images[{id,image,source_path,source_sha256}], options. source_path — абсолютный локальный путь; image — подпись относительно input_root или абсолютная для внешнего файла. options.selection = directory/explicit. В explicit порядок сохраняется, а фон получает selected-inputs.json с выбранными абсолютными путями.
report.json: schema_version, run_id, updated_at, images[{id,image,status,seconds,warnings,error,result_sha256,regions,ocr,translator}].
summary.json: totals, state, seconds, errors, warnings. events.jsonl: timestamp,event,image/id,stage/status.
Состояния: pending → running → done/error; running после прерывания повторяется; error повторяется по --retry-errors. Хеши результатов проверяются при resume.
Оценки: schema_version=1, run_id, exported_at, images[{image,result,status,source_sha256,result_sha256,rating,comment,updated_at}]. localStorage ilt-review:<run_id>; ключи прежних числовых id сохраняются.
