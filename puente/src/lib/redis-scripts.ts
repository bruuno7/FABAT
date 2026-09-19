const TYPES = `
local function valid_type(key, expected)
  local t = redis.call('TYPE', key).ok
  return t == 'none' or t == expected
end
local function decode(raw)
  if not raw then return nil end
  local ok, value = pcall(cjson.decode, raw)
  if not ok or type(value) ~= 'table' then return nil end
  return value
end
local function result(value)
  return cjson.encode(value)
end
`;

export const ENQUEUE_EVENT = TYPES + `
if not valid_type(KEYS[1], 'string') or not valid_type(KEYS[2], 'zset') then
  return result({status='storage_error'})
end
local old = redis.call('GET', KEYS[1])
if old then
  local record = decode(old)
  if not record then return result({status='storage_error'}) end
  if record.fingerprint ~= ARGV[2] then return result({status='event_conflict'}) end
  return result({status='duplicate', event_id=record.event.event_id})
end
local event = cjson.decode(ARGV[1])
redis.call('SET', KEYS[1], result({event=event, fingerprint=ARGV[2], status='pending'}))
redis.call('ZADD', KEYS[2], ARGV[3], event.event_id)
return result({status='accepted', event_id=event.event_id})
`;

export const COMMIT_STATE = TYPES + `
local request = cjson.decode(ARGV[1])
if not valid_type(KEYS[1], 'string') or not valid_type(KEYS[2], 'zset') or
   not valid_type(KEYS[3], 'zset') or not valid_type(KEYS[4], 'stream') then
  return result({status='storage_error'})
end
local inbox = decode(redis.call('GET', KEYS[1]))
if not inbox then return result({status='event_missing'}) end
if type(inbox.event) ~= 'table' or type(inbox.event.event_id) ~= 'string' or
   (inbox.status ~= 'pending' and inbox.status ~= 'applied') then
  return result({status='storage_error'})
end
if inbox.status == 'applied' then
  return result({status='duplicate', event_id=inbox.event.event_id, versions=inbox.versions})
end
local versions = {}
for _, ref in ipairs(request.reads) do
  if not valid_type(KEYS[ref.index], 'string') then return result({status='storage_error'}) end
  local raw = redis.call('GET', KEYS[ref.index])
  local old = decode(raw)
  if raw and (not old or type(old.version) ~= 'number' or type(old.value) ~= 'table') then
    return result({status='storage_error'})
  end
  local version = old and old.version or 0
  if version ~= ref.version then return result({status='conflict', entity=ref.entity}) end
  versions[ref.entity] = version
end
for _, message in ipairs(request.messages) do
  if redis.call('EXISTS', KEYS[message.index]) ~= 0 then
    return result({status='message_conflict'})
  end
end
for _, write in ipairs(request.writes) do
  local version = versions[write.entity] + 1
  redis.call('SET', KEYS[write.index], result({version=version, value=write.value}))
  versions[write.entity] = version
end
for _, message in ipairs(request.messages) do
  redis.call('SET', KEYS[message.index], result({message=message.value, status='pending', attempts=0}))
  redis.call('ZADD', KEYS[3], ARGV[2], message.value.id)
end
redis.call('XADD', KEYS[4], '*', 'event_id', inbox.event.event_id,
           'event', result(inbox.event), 'versions', result(versions))
inbox.status = 'applied'
inbox.versions = versions
redis.call('SET', KEYS[1], result(inbox))
redis.call('ZREM', KEYS[2], inbox.event.event_id)
return result({status='applied', event_id=inbox.event.event_id, versions=versions})
`;

export const CLAIM_MESSAGE = TYPES + `
if not valid_type(KEYS[1], 'string') or not valid_type(KEYS[2], 'zset') then
  return result({status='storage_error'})
end
local record = decode(redis.call('GET', KEYS[1]))
if not record then return result({status='missing'}) end
local now = tonumber(ARGV[1])
if record.status == 'sending' and tonumber(record.lease_until or 0) <= now then
  record.status = 'unknown'
  record.lease = nil
  redis.call('SET', KEYS[1], result(record))
  redis.call('ZREM', KEYS[2], record.message.id)
  return result({status='unknown'})
end
if record.status ~= 'pending' then return result({status=record.status}) end
record.status = 'sending'
record.attempts = record.attempts + 1
record.lease = ARGV[2]
record.lease_until = now + tonumber(ARGV[3])
redis.call('SET', KEYS[1], result(record))
redis.call('ZADD', KEYS[2], record.lease_until, record.message.id)
return result({status='claimed', lease=record.lease, message=record.message, lease_until=record.lease_until})
`;

export const SETTLE_MESSAGE = TYPES + `
if not valid_type(KEYS[1], 'string') or not valid_type(KEYS[2], 'zset') then
  return result({status='storage_error'})
end
local record = decode(redis.call('GET', KEYS[1]))
if not record then return result({status='missing'}) end
if record.status ~= 'sending' or record.lease ~= ARGV[1] then return result({status='lease_conflict'}) end
if tonumber(record.lease_until or 0) <= tonumber(ARGV[4]) then return result({status='lease_expired'}) end
record.status = ARGV[2]
record.provider_message_id = ARGV[3]
record.lease = nil
record.lease_until = nil
redis.call('SET', KEYS[1], result(record))
redis.call('ZREM', KEYS[2], record.message.id)
return result({status=record.status})
`;
