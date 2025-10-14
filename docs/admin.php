<?php
// Simple PHP admin page to manage Customers and API Keys via FastAPI admin endpoints.
// This page now supports in-page configuration stored in PHP session, so you can set API base and ADMIN token without environment variables.
session_start();

// Defaults (align with your FastAPI server)
$defaultBase = 'http://localhost:8100';

// Allow setting config via form (stored in session)
if (($_POST['action'] ?? '') === 'set_config') {
    $_SESSION['API_BASE'] = trim($_POST['API_BASE'] ?? $defaultBase);
    $_SESSION['ADMIN_TOKEN'] = trim($_POST['ADMIN_TOKEN'] ?? '');
}

// Resolve configuration priority: session > env > default
$apiBase = $_SESSION['API_BASE']
    ?? (getenv('API_BASE') ?: $defaultBase);
$adminToken = $_SESSION['ADMIN_TOKEN']
    ?? (getenv('ADMIN_TOKEN') ?: '');

function apiRequest($method, $url, $data = null, $adminToken = '') {
    $opts = [
        'http' => [
            'method' => $method,
            'header' => [
                'Content-Type: application/json',
                'X-Admin-Token: ' . $adminToken,
            ],
            'ignore_errors' => true,
        ]
    ];
    if ($data !== null) {
        $opts['http']['content'] = json_encode($data);
    }
    $context = stream_context_create($opts);
    $resp = file_get_contents($url, false, $context);
    $code = 0;
    if (isset($http_response_header) && preg_match('#\s(\d{3})\s#', $http_response_header[0], $m)) {
        $code = intval($m[1]);
    }
    // Try decode JSON; if not JSON, keep raw body for visibility
    $decoded = json_decode($resp ?? '', true);
    $body = $decoded !== null ? $decoded : $resp;
    return [ 'code' => $code, 'body' => $body ];
}

$action = $_POST['action'] ?? '';
$msg = '';

if ($action === 'create_customer') {
    $email = trim($_POST['email'] ?? '');
    $name = trim($_POST['name'] ?? '');
    $r = apiRequest('POST', $apiBase . '/admin/apikeys/customers', [ 'email' => $email, 'name' => $name ], $adminToken);
    $msg = 'Create customer: HTTP ' . $r['code'];
}
if ($action === 'create_apikey') {
    $cid = intval($_POST['customer_id'] ?? 0);
    $maxp = intval($_POST['max_players'] ?? 100);
    $expires = trim($_POST['expires_at'] ?? '');
    $payload = [ 'customer_id' => $cid, 'max_players' => $maxp ];
    if ($expires !== '') $payload['expires_at'] = $expires; // ISO 8601
    $r = apiRequest('POST', $apiBase . '/admin/apikeys', $payload, $adminToken);
    $msg = 'Create API key: HTTP ' . $r['code'];
}
if ($action === 'update_apikey') {
    $id = intval($_POST['api_key_id'] ?? 0);
    $maxp = $_POST['max_players'] !== '' ? intval($_POST['max_players']) : null;
    $expires = $_POST['expires_at'] !== '' ? $_POST['expires_at'] : null;
    $rev = $_POST['is_revoked'] ?? null; // 'on' or null
    $payload = [];
    if ($maxp !== null) $payload['max_players'] = $maxp;
    if ($expires !== null) $payload['expires_at'] = $expires;
    if ($rev !== null) $payload['is_revoked'] = true;
    $r = apiRequest('PATCH', $apiBase . '/admin/apikeys/' . $id, $payload, $adminToken);
    $msg = 'Update API key: HTTP ' . $r['code'];
}
if ($action === 'revoke_apikey') {
    $id = intval($_POST['api_key_id'] ?? 0);
    $r = apiRequest('POST', $apiBase . '/admin/apikeys/' . $id . '/revoke', null, $adminToken);
    $msg = 'Revoke API key: HTTP ' . $r['code'];
}
if ($action === 'activate_apikey') {
    $id = intval($_POST['api_key_id'] ?? 0);
    $r = apiRequest('POST', $apiBase . '/admin/apikeys/' . $id . '/activate', null, $adminToken);
    $msg = 'Activate API key: HTTP ' . $r['code'];
}

$customersResp = apiRequest('GET', $apiBase . '/admin/apikeys/customers', null, $adminToken);
$keysResp = apiRequest('GET', $apiBase . '/admin/apikeys', null, $adminToken);
$customers = is_array($customersResp['body']) ? $customersResp['body'] : [];
$keys = is_array($keysResp['body']) ? $keysResp['body'] : [];
?>
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Admin - Customers & API Keys</title>
<style>
body{font-family:sans-serif;margin:20px}
fieldset{margin:10px 0;padding:10px}
label{display:block;margin:6px 0}
input[type=text],input[type=number]{width:320px}
table{border-collapse:collapse;margin-top:10px}
th,td{border:1px solid #ccc;padding:6px 8px}
.msg{padding:8px;background:#eef;border:1px solid #99f;margin-bottom:10px}
.cfg{padding:8px;background:#f9f9f9;border:1px solid #ddd;margin-bottom:10px}
</style>
</head>
<body>
<h1>Admin - Customers & API Keys</h1>
<div class="cfg">
    <form method="post" style="display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap">
        <div>
            <label>API Base (ex: http://localhost:8100)
                <input type="text" name="API_BASE" value="<?= htmlspecialchars($apiBase) ?>" />
            </label>
        </div>
        <div>
            <label>Admin Token (X-Admin-Token)
                <input type="text" name="ADMIN_TOKEN" value="<?= htmlspecialchars($adminToken) ?>" />
            </label>
        </div>
        <input type="hidden" name="action" value="set_config" />
        <button type="submit">Save Config</button>
        <div style="color:#666">Env fallback: API_BASE / ADMIN_TOKEN</div>
    </form>
</div>

<?php if ($msg) { echo '<div class="msg">' . htmlspecialchars($msg) . '</div>'; } ?>

<form method="post">
<fieldset>
<legend>Create Customer</legend>
<label>Email: <input type="text" name="email" required /></label>
<label>Name: <input type="text" name="name" /></label>
<input type="hidden" name="action" value="create_customer" />
<button type="submit">Create</button>
</fieldset>
</form>

<form method="post">
<fieldset>
<legend>Create API Key</legend>
<label>Customer ID: <input type="number" name="customer_id" required /></label>
<label>Max Players (2-500): <input type="number" name="max_players" min="2" max="500" value="100" /></label>
<label>Expires At (ISO8601): <input type="text" name="expires_at" placeholder="2025-12-31T23:59:59Z" /></label>
<input type="hidden" name="action" value="create_apikey" />
<button type="submit">Create</button>
</fieldset>
</form>

<h2>Customers</h2>
<?php if ($customersResp['code'] !== 200) { ?>
    <div class="msg">GET /admin/apikeys/customers → HTTP <?= htmlspecialchars((string)$customersResp['code']) ?>
    <div><pre style="white-space:pre-wrap;max-width:960px;overflow:auto"><?php echo htmlspecialchars(is_string($customersResp['body']) ? $customersResp['body'] : json_encode($customersResp['body'], JSON_PRETTY_PRINT)); ?></pre></div>
    </div>
<?php } ?>
<table>
<thead><tr><th>ID</th><th>Email</th><th>Name</th><th>Active</th><th>Created</th></tr></thead>
<tbody>
<?php foreach ($customers as $c): ?>
<tr>
<td><?= htmlspecialchars($c['id']) ?></td>
<td><?= htmlspecialchars($c['email']) ?></td>
<td><?= htmlspecialchars($c['name'] ?? '') ?></td>
<td><?= !empty($c['is_active']) ? 'Yes' : 'No' ?></td>
<td><?= htmlspecialchars($c['created_at'] ?? '') ?></td>
</tr>
<?php endforeach; ?>
</tbody>
</table>

<h2>API Keys</h2>
<?php if ($keysResp['code'] !== 200) { ?>
    <div class="msg">GET /admin/apikeys → HTTP <?= htmlspecialchars((string)$keysResp['code']) ?>
    <div><pre style="white-space:pre-wrap;max-width:960px;overflow:auto"><?php echo htmlspecialchars(is_string($keysResp['body']) ? $keysResp['body'] : json_encode($keysResp['body'], JSON_PRETTY_PRINT)); ?></pre></div>
    </div>
<?php } ?>
<table>
<thead><tr><th>ID</th><th>Key</th><th>Customer</th><th>Max Players</th><th>Expires</th><th>Revoked</th><th>Actions</th></tr></thead>
<tbody>
<?php foreach ($keys as $k): ?>
<tr>
<td><?= htmlspecialchars($k['id']) ?></td>
<td style="font-family:monospace;max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="<?= htmlspecialchars($k['key']) ?>"><?= htmlspecialchars($k['key']) ?></td>
<td><?= htmlspecialchars($k['customer_id']) ?></td>
<td><?= htmlspecialchars($k['max_players']) ?></td>
<td><?= htmlspecialchars($k['expires_at'] ?? '') ?></td>
<td><?= !empty($k['is_revoked']) ? 'Yes' : 'No' ?></td>
<td>
<form method="post" style="display:inline-block">
<input type="hidden" name="action" value="update_apikey" />
<input type="hidden" name="api_key_id" value="<?= htmlspecialchars($k['id']) ?>" />
<input type="number" name="max_players" min="2" max="500" placeholder="max" />
<input type="text" name="expires_at" placeholder="2025-12-31T23:59:59Z" />
<label><input type="checkbox" name="is_revoked" <?= !empty($k['is_revoked']) ? 'checked' : '' ?> /> Revoked</label>
<button type="submit">Update</button>
</form>
<form method="post" style="display:inline-block;margin-left:6px">
<input type="hidden" name="api_key_id" value="<?= htmlspecialchars($k['id']) ?>" />
<input type="hidden" name="action" value="revoke_apikey" />
<button type="submit">Revoke</button>
</form>
<form method="post" style="display:inline-block;margin-left:6px">
<input type="hidden" name="api_key_id" value="<?= htmlspecialchars($k['id']) ?>" />
<input type="hidden" name="action" value="activate_apikey" />
<button type="submit">Activate</button>
</form>
</td>
</tr>
<?php endforeach; ?>
</tbody>
</table>

<p style="margin-top:20px;color:#666">Configure via env: API_BASE (default http://localhost:8000), ADMIN_TOKEN.</p>
</body>
</html>
