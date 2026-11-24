-- Print subject and not_after of an X.509 certificate without openssl.
-- Usage: lua ca-print.lua <cert.pem|cert.der>
-- Output (strongSwan-like):
--   subject:  "C=.., CN=.."
--   not after  Mon DD HH:MM:SS YYYY

local path = arg[1]
if not path or path == '' then
	io.stderr:write('usage: lua ca-print.lua <cert>\n')
	os.exit(1)
end

local f = io.open(path, 'rb')
if not f then
	os.exit(1)
end
local data = f:read('*a') or ''
f:close()
if data == '' then
	os.exit(1)
end

local b64chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local b64map = {}
for i = 1, #b64chars do
	b64map[b64chars:sub(i, i)] = i - 1
end

local function b64decode(s)
	s = s:gsub('%s+', '')
	local out = {}
	local i = 1
	while i <= #s do
		local chunk = s:sub(i, i + 3)
		i = i + 4
		local c = {0, 0, 0, 0}
		local bytes = 0
		for j = 1, #chunk do
			local ch = chunk:sub(j, j)
			if ch ~= '=' then
				c[j] = b64map[ch]
				if not c[j] then
					return nil
				end
				bytes = j
			end
		end
		if bytes < 2 then
			return nil
		end
		local n = c[1] * 262144 + c[2] * 4096 + c[3] * 64 + c[4]
		out[#out + 1] = string.char(math.floor(n / 65536) % 256)
		if bytes >= 3 then
			out[#out + 1] = string.char(math.floor(n / 256) % 256)
		end
		if bytes >= 4 then
			out[#out + 1] = string.char(n % 256)
		end
	end
	return table.concat(out)
end

local der = data
local bpos = data:find('-----BEGIN CERTIFICATE-----', 1, true)
local epos = data:find('-----END CERTIFICATE-----', 1, true)
if bpos and epos and epos > bpos then
	local pem = data:sub(bpos + #('-----BEGIN CERTIFICATE-----'), epos - 1)
	der = b64decode(pem)
end
if not der or #der < 8 then
	os.exit(1)
end

local function fail()
	os.exit(1)
end

local function read_len(s, i)
	if i > #s then fail() end
	local b = s:byte(i)
	if b < 128 then
		return b, i + 1
	end
	local n = b - 128
	if n == 0 or n > 4 or i + n > #s then fail() end
	local len = 0
	for j = 1, n do
		len = len * 256 + s:byte(i + j)
	end
	return len, i + n + 1
end

-- Returns tag, class (0=univ,1=app,2=ctx,3=priv), constructed, value, nextindex
local function read_tlv(s, i)
	if i > #s then fail() end
	local b = s:byte(i)
	local class = math.floor(b / 64)
	local constructed = math.floor(b / 32) % 2 == 1
	local tag = b % 32
	i = i + 1
	if tag == 31 then
		tag = 0
		repeat
			if i > #s then fail() end
			b = s:byte(i)
			i = i + 1
			tag = tag * 128 + (b % 128)
		until b < 128
	end
	local len
	len, i = read_len(s, i)
	if i + len - 1 > #s then fail() end
	return tag, class, constructed, s:sub(i, i + len - 1), i + len
end

local function parse_oid(s)
	if #s < 1 then return '' end
	local first = s:byte(1)
	local parts = { math.floor(first / 40), first % 40 }
	local acc = 0
	for i = 2, #s do
		local b = s:byte(i)
		acc = acc * 128 + (b % 128)
		if b < 128 then
			parts[#parts + 1] = acc
			acc = 0
		end
	end
	return table.concat(parts, '.')
end

local oid_attr = {
	['2.5.4.3'] = 'CN',
	['2.5.4.6'] = 'C',
	['2.5.4.7'] = 'L',
	['2.5.4.8'] = 'ST',
	['2.5.4.10'] = 'O',
	['2.5.4.11'] = 'OU',
	['1.2.840.113549.1.9.1'] = 'emailAddress'
}

local function parse_string(tag, value)
	if tag == 30 then -- BMPString UCS-2
		local chars = {}
		for i = 1, #value, 2 do
			local code = value:byte(i) * 256 + (value:byte(i + 1) or 0)
			if code < 128 then
				chars[#chars + 1] = string.char(code)
			elseif code < 0x800 then
				chars[#chars + 1] = string.char(192 + math.floor(code / 64), 128 + (code % 64))
			else
				chars[#chars + 1] = '?'
			end
		end
		return table.concat(chars)
	end
	return value
end

local function parse_name(blob)
	local rdns, i = {}, 1
	while i <= #blob do
		-- RDN is SET
		local tag, class, constructed, setv
		tag, class, constructed, setv, i = read_tlv(blob, i)
		if not (class == 0 and tag == 17) then
			-- skip unexpected
		else
			local j = 1
			while j <= #setv do
				local atv
				tag, class, constructed, atv, j = read_tlv(setv, j)
				if class == 0 and tag == 16 then
					local k, oidv, valv = 1
					tag, class, constructed, oidv, k = read_tlv(atv, k)
					if class == 0 and tag == 6 then
						local oid = parse_oid(oidv)
						local vtag, vclass, vcons, vval
						vtag, vclass, vcons, vval = read_tlv(atv, k)
						local short = oid_attr[oid]
						if short then
							rdns[#rdns + 1] = short .. '=' .. parse_string(vtag, vval)
						end
					end
				end
			end
		end
	end
	return table.concat(rdns, ', ')
end

local months = { 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
	'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec' }

local function format_time(tag, value)
	-- UTCTime YYMMDDHHMMSSZ or GeneralizedTime YYYYMMDDHHMMSSZ
	local y, mo, d, h, mi, se
	if tag == 24 or #value >= 14 then
		y = tonumber(value:sub(1, 4))
		mo = tonumber(value:sub(5, 6))
		d = tonumber(value:sub(7, 8))
		h = tonumber(value:sub(9, 10))
		mi = tonumber(value:sub(11, 12))
		se = tonumber(value:sub(13, 14)) or 0
	else
		y = tonumber(value:sub(1, 2))
		if not y then return value end
		if y >= 50 then y = 1900 + y else y = 2000 + y end
		mo = tonumber(value:sub(3, 4))
		d = tonumber(value:sub(5, 6))
		h = tonumber(value:sub(7, 8))
		mi = tonumber(value:sub(9, 10))
		se = tonumber(value:sub(11, 12)) or 0
	end
	if not (y and mo and d and h and mi and se and months[mo]) then
		return value
	end
	return string.format('%s %02d %02d:%02d:%02d %04d', months[mo], d, h, mi, se, y)
end

-- Certificate ::= SEQUENCE { tbsCertificate SEQUENCE { ... }, ... }
local tag, class, constructed, cert
tag, class, constructed, cert = read_tlv(der, 1)
if not (class == 0 and tag == 16 and constructed) then
	fail()
end
local tbs
tag, class, constructed, tbs = read_tlv(cert, 1)
if not (class == 0 and tag == 16 and constructed) then
	fail()
end

local i = 1
local fields = {}
while i <= #tbs do
	local val, ni
	tag, class, constructed, val, ni = read_tlv(tbs, i)
	fields[#fields + 1] = { tag = tag, class = class, constructed = constructed, val = val }
	i = ni
end

-- TBSCertificate fields after optional version:
-- serial(INTEGER), signature(SEQUENCE), issuer(Name SEQ), validity(SEQ), subject(Name SEQ)
local idx = 1
if fields[1] and fields[1].class == 2 and fields[1].tag == 0 then
	idx = 2
end
-- fields from idx: serial, signature, issuer, validity, subject
local validity_field = fields[idx + 3]
local subject_field = fields[idx + 4]
if not validity_field or not subject_field then
	fail()
end

local subject = parse_name(subject_field.val)
local not_after = '-'
do
	local v = validity_field.val
	local j, t1, c1, cons1, v1, t2, c2, cons2, v2
	t1, c1, cons1, v1, j = read_tlv(v, 1)
	t2, c2, cons2, v2, j = read_tlv(v, j)
	not_after = format_time(t2, v2)
end

if subject == '' then
	fail()
end

io.write('  subject:  "', subject, '"\n')
io.write('  not after  ', not_after, '\n')
