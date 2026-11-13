# Contracts

Host IPC: {"paths":["absolute file",...],"mode":"quick"|"editor"}; absent mode = editor. --quick consumed by host, never a source path. Startup requests wait for API handshake; paths not lost.

Local /api/quick/* require existing local API authentication and are blocked on LAN/browser surface:
- GET session -> {items,selected_id,busy,server:{url,paired}}; no token.
- POST accept {paths:string[]} -> session; last selected; valid inputs auto-upload sequentially.
- POST select/cancel/retry/remove {id} -> session. Retry bypasses server cache.
- GET image/<id>/<original|result> -> PNG for Flutter.
- POST save {id,path,overwrite:false} -> {path}; existing file 409, source always protected.
- POST bug-report {id,note} -> local {path}.
- POST editor {id} -> new independent editor project; root guards unsaved edits before request.
- POST server {url,code?} -> session. Pair /v1/pair when code supplied; token stored separately. Busy -> 409.

Remote: same protocol as extension/src/background.js:
1. GET /v1/health -> max_body_bytes/version.
2. POST /v1/pair {code,name} -> token.
3. POST /v1/translate multipart file,target_lang,optional fresh=1; Bearer.
4. GET /v1/jobs/<id>?diagnostics=1 -> standard status fields; optional diagnostics:{settings,warnings}. Old server ignores query and remains compatible.
5. GET /v1/jobs/<id>/result -> PNG.
6. DELETE /v1/jobs/<id> after download, error or cancel. Updated server stops active worker job on DELETE. Old server removes the record; active processing may finish in background.

Native ilt/windows: showQuick({port,token}), getApi, showEditor({quick_item_id?}), hide, visibleEditor, visibleQuick, quit, exit. API credential passed in memory, not CLI. --quick-view child starts no sidecar/IPC/ShellState.
