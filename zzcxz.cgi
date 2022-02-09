#!/usr/bin/env lua5.3
-- this software is licensed under the terms of the GNU affero public license
-- v3 or later. view LICENSE.txt for more information.

-- if you host your own instance, please change the email address in the about
-- page and clearly distinguish your instance from https://zzcxz.citrons.xyz.

local env = os.getenv

local f = io.open("/dev/urandom", 'r')
local e = f and f:read(1)
if f then f:close() end
math.randomseed(os.time() + string.byte(e))

local function url_encode(str)
	return (str:gsub("([^A-Za-z0-9%_%.%-%~])", function(v)
		return string.upper(string.format("%%%02x", string.byte(v)))
	end))
end

local esc_sequences = {
	["<"] = "&lt;",
	[">"] = "&gt;",
	['"'] = "&quot;"
}
local function html_encode(x)
	local escaped = tostring(x)
	escaped = escaped:gsub("&", "&amp;")

	for char,esc in pairs(esc_sequences) do
		escaped = string.gsub(escaped, char, esc)
	end
	return escaped
end

local function parse_qs(str,sep)
	sep = sep or '&'
	local function decode(str, path)
		local str = str
		if not path then
			str = str:gsub('+', ' ')
		end
		str = str:gsub("%%(%x%x)", function(c)
				return string.char(tonumber(c, 16))
		end)
		return (str:gsub('\r\n', '\n'))
	end

	local values = {}
	for key,val in str:gmatch(string.format('([^%q=]+)(=*[^%q=]*)', sep, sep)) do
		local key = decode(key)
		local keys = {}
		key = key:gsub('%[([^%]]*)%]', function(v)
				-- extract keys between balanced brackets
				if string.find(v, "^-?%d+$") then
					v = tonumber(v)
				else
					v = decode(v)
				end
				table.insert(keys, v)
				return "="
		end)
		key = key:gsub('=+.*$', "")
		key = key:gsub('%s', "_") -- remove spaces in parameter name
		val = val:gsub('^=+', "")

		if not values[key] then
			values[key] = {}
		end
		if #keys > 0 and type(values[key]) ~= 'table' then
			values[key] = {}
		elseif #keys == 0 and type(values[key]) == 'table' then
			values[key] = decode(val)
		end

		local t = values[key]
		for i,k in ipairs(keys) do
			if type(t) ~= 'table' then
				t = {}
			end
			if k == "" then
				k = #t+1
			end
			if not t[k] then
				t[k] = {}
			end
			if i == #keys then
				t[k] = decode(val)
			end
			t = t[k]
		end
	end
	return values
end

local cookies = env "HTTP_COOKIE" and parse_qs(env "HTTP_COOKIE","; ") or {}
local history = {}
if cookies.history then
	for page in cookies.history:gmatch "(%w%w%w%w%w)%," do
		table.insert(history, page)
	end
end

local function redirect(to)
	return "", {
		status = '303 see other',
		headers = { location = to },
	}
end

local function template(str)
	return function (t)
		return (str:gsub("$([A-Za-z][A-Za-z0-9]*)", function(v)
			return t[v] or ""
		end))
	end
end

local base = template [[
<!doctype html>
<html>
	<head>
		<link rel="stylesheet" href="/static/amethyst.css" />
		<meta charset="utf-8"/>
		<title>zzcxz: $title</title>
		<meta name="viewport" content="width=device-width, initial-scale=1">
	</head>
	<body>
		<h1>zzcxz</h1>
		<main>$content</main>
		<footer>
			<div class="links">
				<p><a href="/g/zzcxz">back to start</a></p>
				<p><a href="/about">help</a></p>
				<p><a href="https://citrons.xyz/git/zzcxz.git/about">
					source code
				</a></p>
				<p><a href="https://citrons.xyz">citrons.xyz</a></p>
			</div>
		</footer>
	</body>
</html>
]]

local not_found = function() 
	return
		base {
			title = "not found",
			content = "the content requested was not found.",
		}, { status = '404 not found' }
end

local function parse_directive(line, directives)
	local directive, args = line:match "^#([A-Za-z]+)%s*(.-)\n?$"
	directive = directive and directive:lower()
	if not directive then
		return
	elseif directive == "redirect" then
		local redirect = args:match "^%s*(%w%w%w%w%w)%s*$"
		if not redirect then return end
		directives.redirect = redirect
	else
		return
	end
	return true
end

local load_page
local function convert_markup(m)
	local result = {}
	local directives = {}
	local code_block = false
	for line in (m..'\n'):gmatch "(.-)\n" do
		if not code_block then
			if line:match "^%s*$" then
				goto continue
			end
			if line:sub(1,1) == '#' and
					parse_directive(line, directives) then
				if directives.redirect then
					local to = load_page(directives.redirect)
					if to then
						local m, d = convert_markup(to.content)
						-- the final destination will not have a redirect
						-- value in this directive. as such, this will store
						-- final destination of a chain of redirects.
						d.redirect = d.redirect or to
						return m, d
					else
						directives.redirect = nil
					end
				else
					goto continue
				end
			end

			line = html_encode(line)
			if line:sub(1,1) == ' ' then
				table.insert(result, '<pre><code>')
				code_block = true
			else
				line = line:gsub("\\\\([%[%]])", "&#92;%1")
				line = line:gsub("\\([%[%]])", 
					{ ['['] = "&#91;", [']'] = "&#93;" })
				line = line:gsub("%[(.-)%]",
					function(s)
						return ('<span class="important">%s</span>'):format(s)
					end
				)
				table.insert(result, ('<p>%s</p>'):format(line))
			end
		end
		if code_block then
			if line:sub(1,1) == ' ' then
				table.insert(result, line .. '\n') 
			else
				table.insert(result, '</code></pre>')
				code_block = false
			end
		end
		::continue::
	end
	if code_block then
		table.insert(result, '</code></pre>')
		code_block = false
	end

	return table.concat(result), directives
end

local function parse_page(s)
	local page = {}
	page.title = s:match "^(.-)\n"
	page.actions = {}
	local content = {}
	for line in (s..'\n'):gmatch "(.-\n)" do
		if line:sub(1,1) == '\t' then
			table.insert(content, line:sub(2))
		elseif line:match("^!image")  then
			page.illustration = line:match "^!image%s+(%w+)"
		else
			local target, action = line:match "^(%w%w%w%w%w):(.-)\n$"
			if action then
				table.insert(page.actions, {action = action, target = target})
			end
		end
	end
	page.content = table.concat(content)

	return page
end

function load_page(p, raw)
	if not p:match("^%w%w%w%w%w$") then return nil end
	local f, bee = io.open('content/'..p)
	if not f then return nil end
	local s = f:read "a"
	f:close()
	if not s then return nil end
	if raw then return s end
	local page = parse_page(s)
	page.id = p
	return page
end

local function new_action(page, action, result)
	local _, directives = convert_markup(result)

::generate_name::
	local new_name = {}
	for i=1,5 do
		table.insert(new_name, string.char(string.byte 'a' + math.random(0,25)))
	end
	new_name = table.concat(new_name)

	local exists = io.open('content/'..new_name, 'r')
	if exists then
		exists:close()
		goto generate_name
	end

	local old = assert(io.open('content/'..page, 'a'))
	local new = assert(io.open('content/'..new_name, 'w'))

	action = action:gsub('\n', ' ')
	assert(new:write(action..'\n'))
	for line in (result..'\n'):gmatch "(.-\n)" do
		assert(new:write('\t' .. line))
	end
	assert(old:write(('%s:%s\n'):format(new_name, action)))

	if directives.backlinks then
		for _,d in ipairs(directives.backlinks) do
			assert(new:write(('%s:%s\n'):format(d.page, d.action)))
		end
	end

	new:close()
	old:close()

	return new_name
end

local hist_template = template [[
	<ul class="hist-log">
		$log
	</ul>
]]
local function show_hist(show_ids)
	local log = {}
	if #history == 0 then return "" end

	for i=#history,1,-1 do
		local page = load_page(history[i])
		if not page then goto continue end

		-- highlight the current page
		local title = i ~= #history and html_encode(page.title)
			or '<strong>'..html_encode(page.title)..'</strong>'
		if show_ids then
			table.insert(log,
				('<li>%s <span class="page-id">%s</span></li>')
					:format(title, history[i]))
		else
			table.insert(log, ('<li>%s</li>'):format(title))
		end
		::continue::
	end
	return hist_template {
		log = table.concat(log),
	}
end

local map = {}

local page_template = template [[
	<h2>$title</h2>
	$illustration
	$content
	$drawthis
	<ul class="actions">
	$actions
	</ul>
	$log
]]
local draw_this = [[
	<p id="draw-this"><a href="$page/illustrate">illustrate this</a></p>
]]
map["^/g/(%w%w%w%w%w)$"] = function(p)
	local page = load_page(p)
	if not page then return not_found() end
	local content, directives = convert_markup(page.content)

	if env "REQUEST_METHOD" ~= "POST" then
		if history[#history] ~= p then
			table.insert(history, p)
		end
		if #history > 75 then
			table.remove(history, 1)
		end

		local title = page.title

		if directives.redirect then
			page = directives.redirect
		end

		local actions = {}
		for _,a in ipairs(page.actions) do
			table.insert(actions,
				('<li><a href="%s">%s</a></li>'):format(
					html_encode(a.target), html_encode(a.action)))
		end
		if not directives.deadend then
			table.insert(actions,
				([[
					<li><a class="important" href="%s/act#what">%s</a></li>
				]]):format(page.id, #page.actions == 0 and
					"do something..." or "do something else...")
			)
		end

		local illustration, draw_this
		if page.illustration then
			illustration = ([[
				<img class="illustration" src="/i/%s.%s" />
			]]):format(page.id, page.illustration)
		else
--			draw_this = ([[
--				<p id="draw-this"><a href="%s/illustrate">
--					illustrate this
--				</a></p>
--			]]):format(p)
		end

		local hist_cookie = ('history=%s; path=/; secure; max-age=99999999999')
			:format(table.concat(history, ',')..',')

		return base {
			title = html_encode(title),
			content = page_template {
				title = html_encode(title),
				content = content,
				actions = table.concat(actions),
				illustration = illustration,
				drawthis = draw_this,
				log = show_hist(),
			},
		}, { headers = { ['set-cookie'] = hist_cookie } }
	else
		if directives.deadend then
			return base {
				title = "error",
				content = "forbidden",
			}, { status = '403 forbidden' }
		end

		local form = parse_qs(io.read "a")

		form.wyd = form.wyd or "something"
		form.happens = form.happens or "something"
		if utf8.len(form.wyd) > 150 then form.wyd = "something" end
		if utf8.len(form.happens) > 10000 then form.wyd = "something" end

		local new = new_action(p, form.wyd, form.happens)
		return redirect("/g/"..new)
	end
end

map["^/g/(%w%w%w%w%w)/$"] = function(p)
	return redirect('/g/'..p)
end

local edit_template = template [[
	$content
	<hr id="what"/>
	$preview
	<form method="POST">
		<p>
			<a href="/about#rules">READ THIS</a> before touching anything.
		</p>
		<h2>what do you do?</h2>
		<input
			type="text"
			id="wyd" name="wyd"
			value="$title"
			maxlength="150" required
		/>
		<h2>what happens next?</h2>
		<textarea
			id="happens" name="happens"
			maxlength="10000" required
		>$editing</textarea>
		<div class="buttons">
			<a href="../$page">cancel</a>
			<input type="submit" formaction="act#what" value="preview" />
			$submit
		</div>
		$log
	</form>
]]
local preview_template = template [[
	<h2>$title</h2>
	$content
	<hr />
]]
local submit_template = template [[
	<input type="submit" formaction="/g/$page" value="submit" />
]]
map["^/g/(%w%w%w%w%w)/act$"] = function(p)
	local page = load_page(p)
	if not page then return not_found() end

	local _, directives = convert_markup(page.content)
	if directives.deadend then return not_found() end

	if env "REQUEST_METHOD" ~= "POST" then
		return base {
			title = "do something new",
			content = edit_template {
				page = p,
				content = convert_markup(page.content),
				log = show_hist(true),
			},
		}
	else
		local form = parse_qs(io.read "a")
		form.wyd = form.wyd or "something"
		form.happens = form.happens or "something"

		local prev, prev_direct = convert_markup(form.happens)

		local prev_title =
			prev_direct.title and html_encode(prev_direct.title) or
				html_encode(form.wyd)

		if prev_direct.redirect then
			local note =
				('<span class="note">previewing %s</span>')
					:format(prev_direct.redirect.id)
			prev = note..prev
		end
		
		return base {
			title = "do something new",
			content = edit_template {
				page = p,
				content = convert_markup(page.content),
				preview = preview_template {
					title = prev_title,
					content = prev,
				},
				title = html_encode(form.wyd),
				editing = html_encode(form.happens),
				submit = submit_template { page = p },
				log = show_hist(true),
			},
		}
	end
end

local illustrate_template = template [[
	<h2>$title</h2>
	$content
	<hr/>
	<h2 id="what">what does this look like?</h2>
	<form method="POST" action="/g/$page/illustrate"
			enctype="multipart/form-data" id="img-form">
		<input
			type="file"
			name="file"
			accept="image/png,image/jpeg,image/gif"
		/>
		<input type="submit" value="submit image" />
	</form>
]]
-- map["^/g/(%w%w%w%w%w)/illustrate"] = function(p)
-- 	local page = load_page(p)
-- 	if not page then return not_found() end
-- 
-- 	if env "REQUEST_METHOD" ~= "POST" then
-- 		return base {
-- 			title = "illustration: " .. html_encode(page.title),
-- 			content = illustrate_template {
-- 				title = html_encode(page.title),
-- 				content = convert_markup(page.content),
-- 				page = p,
-- 			},
-- 		}
-- 	else
-- 	end
-- end

map["^/i/(%w%w%w%w%w).(%w+)$"] = function(p, format)
	local page = load_page(p)
	if not page or
			not page.illustration or not page.illustration == format then
		return not_found()
	end
	return
		assert(io.open(('content/%s.%s'):format(p, format), 'r')),
		{ content_type = 'image/'..format }
end

map["^/g/(%w%w%w%w%w)/raw$"] = function(p)
	local page = load_page(p, true)
	if not page then return not_found() end

	return page, {
		content_type = 'text/plain',
		headers = { ['access-control-allow-origin'] = "*" }
	}
end

map["^/about/?$"] = function()
	return assert(io.open("about.html", 'r'))
end

map["^/robots.txt$"] = function()
	return assert(io.open("robots.txt", 'r')),
		{ content_type = 'text/plain' }
end

map["^/$"] = function()
	if #history > 0 then
		return redirect('/g/'..history[#history])
	else
		return redirect '/g/zzcxz'
	end
end

local function main()
	for k,v in pairs(map) do
		local m = {(env "PATH_INFO"):match(k)}
		if m[1] then
			return v(table.unpack(m))
		end
	end
	return not_found()
end

local ok, content, resp = pcall(main)
if not ok or (type(content) ~= 'string' and type(content) ~= 'userdata') then
	io.stderr:write(content..'\n')

	content = base {
		title = "internal error",
		content = "an internal error occurred."
	}
	resp = { status = '500 internal server error' }
end

resp = resp or {}
resp.content_type = resp.content_type or 'text/html'
resp.status = resp.status or '200 OK'
resp.headers = resp.headers or {}
resp.headers['content-type'] = resp.content_type

print("status: "..resp.status)
for k,v in pairs(resp.headers) do
	print(("%s: %s"):format(k, v))
end

print ""
if type(content) == 'string' then
	io.write(content)
else
	while 1 do
		local data = content:read(1024)
		if not data then break end
		io.write(data)
	end
end
