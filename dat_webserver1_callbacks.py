# me - this DAT.
# webServerDAT - the connected Web Server DAT
# request - A dictionary of the request fields.
# response - A dictionary defining the response.
#
# Modernized OSCQuery WebServer Callbacks
# - JSON-based WebSocket protocol for reliable multi-client sync
# - Auto-subscribe all clients on connect (no manual LISTEN needed)
# - Broadcasts value changes to ALL other connected clients
# - Backwards-compatible with binary OSC WebSocket messages

import osc_parse_module as osclib
import json


# ---------------------------------------------------------------------------
# Helper: get the authoritative list of connected WebSocket clients
# directly from the Web Server DAT (survives DAT recompilation).
# ---------------------------------------------------------------------------
def _get_clients(webServerDAT=None):
	"""Return a snapshot list of all connected WS clients."""
	try:
		if webServerDAT is None:
			webServerDAT = op("webserver1")
		return list(webServerDAT.webSocketConnections)
	except Exception:
		return []


# ===========================================================================
# HTTP
# ===========================================================================

def onHTTPRequest(webServerDAT, request, response):
	uri = request["uri"]
	uriSegments = uri.split("/")

	# Serve the modern web client assets
	if "client.js" in request["pars"]:
		response = _ok(response, "application/javascript")
		response["data"] = op("web_assets/client_js").text

	elif "style.css" in request["pars"]:
		response = _ok(response, "text/css")
		response["data"] = op("web_assets/style_css").text

	elif uri == "/ui":
		response = _ok(response, "text/html")
		html = op("web_assets/edit_html").text
		html = html.replace("{{OSCQUERY_HOST}}", request["serverAddress"])
		response["data"] = html

	elif len(uriSegments) > 1 and uriSegments[1] == "fonts":
		pass  # ignore font requests

	else:
		try:
			response = _ok(response, "application/json")
			response["Access-Control-Allow-Origin"] = "*"
			response["data"] = parent().GetJson(uri, request["pars"])
		except Exception:
			response = _notFound(response)
			response["data"] = _buildNotFoundPage()

	return response


# ===========================================================================
# WebSocket – lifecycle
# ===========================================================================

def onWebSocketOpen(webServerDAT, client):
	print("[OSCQuery] Client connected: " + client)

	# Auto-subscribe this client to ALL addresses so it receives updates
	# immediately without needing to manually click "Listen".
	try:
		allAddresses = parent().GetAllAddresses()
		for addr in allAddresses:
			parent().AddToListen(addr, client)
	except Exception as e:
		print("[OSCQuery] Could not auto-listen: " + str(e))

	# Broadcast updated client count to ALL connected clients
	_broadcastClientCount(webServerDAT)
	return


def onWebSocketClose(webServerDAT, client):
	print("[OSCQuery] Client disconnected: " + client)

	# Clean up listen entries for this client
	try:
		allAddresses = parent().GetAllAddresses()
		for addr in allAddresses:
			try:
				parent().RemoveFromListen(addr, client)
			except Exception:
				pass
	except Exception:
		pass

	# Notify remaining clients of updated connection count
	_broadcastClientCount(webServerDAT)
	return


# ===========================================================================
# WebSocket – receive text (JSON protocol)
# ===========================================================================

def onWebSocketReceiveText(webServerDAT, client, data):
	try:
		# Robust JSON parsing – handle trailing garbage from old clients
		braceDepth = 0
		endIdx = -1
		for i, ch in enumerate(data):
			if ch == '{':
				braceDepth += 1
			elif ch == '}':
				braceDepth -= 1
				if braceDepth == 0:
					endIdx = i
					break
		if endIdx < 0:
			return
		obj = json.loads(data[:endIdx + 1])
	except Exception as e:
		print("[OSCQuery] Bad JSON from " + client + ": " + str(e))
		return

	command = obj.get("COMMAND", "")

	# --- Legacy LISTEN / IGNORE (kept for backwards compat) ---------------
	if command == "LISTEN":
		parent().AddToListen(obj["DATA"], client)

	elif command == "IGNORE":
		parent().RemoveFromListen(obj["DATA"], client)

	# --- LISTEN_ALL: subscribe to everything in one go --------------------
	elif command == "LISTEN_ALL":
		try:
			allAddresses = parent().GetAllAddresses()
			for addr in allAddresses:
				parent().AddToListen(addr, client)
		except Exception:
			pass

	# --- SET: new JSON-based value change from web UI ---------------------
	elif command == "SET":
		address = obj.get("ADDRESS", "")
		args = obj.get("ARGS", [])

		if address:
			# Apply the value in TouchDesigner
			parent().ReceiveOsc(address, args)

			# Broadcast the change to ALL OTHER connected clients
			update = json.dumps({
				"COMMAND": "VALUE_UPDATE",
				"ADDRESS": address,
				"ARGS": args
			})
			for c in _get_clients(webServerDAT):
				if c != client:
					try:
						webServerDAT.webSocketSendText(c, update)
					except Exception:
						pass

	# --- PING: keep-alive -------------------------------------------------
	elif command == "PING":
		try:
			webServerDAT.webSocketSendText(client, json.dumps({"COMMAND": "PONG"}))
		except Exception:
			pass

	return


# ===========================================================================
# WebSocket – receive binary (OSC packets from legacy clients)
# ===========================================================================

def onWebSocketReceiveBinary(webServerDAT, client, data):
	try:
		msg = osclib.decode_packet(data)
	except Exception as e:
		print("[OSCQuery] Failed to decode binary OSC: " + str(e))
		return

	oscAddress = msg.addrpattern
	oscArgs = []

	for arg in msg.arguments:
		if hasattr(arg, "red"):
			for c in arg:
				oscArgs.append(c / 255)
		oscArgs.append(arg)

	# Apply in TouchDesigner
	parent().ReceiveOsc(oscAddress, oscArgs)

	# Also broadcast as JSON VALUE_UPDATE to all other clients
	# so modern JSON-based clients stay in sync
	update = json.dumps({
		"COMMAND": "VALUE_UPDATE",
		"ADDRESS": oscAddress,
		"ARGS": oscArgs
	})
	for c in _get_clients(webServerDAT):
		if c != client:
			try:
				webServerDAT.webSocketSendText(c, update)
			except Exception:
				pass

	return


def onWebSocketReceivePing(webServerDAT, client, data):
	return


def onWebSocketReceivePong(webServerDAT, client, data):
	return


# ===========================================================================
# Server lifecycle
# ===========================================================================

def onServerStart(webServerDAT):
	print("[OSCQuery] Server started")
	return


def onServerStop(webServerDAT):
	print("[OSCQuery] Server stopped")
	return


# ===========================================================================
# Helper: broadcast from TD parameter changes to ALL connected clients
# This is called from noise.py / parexec_template.py via:
#   op("../webserver1_callbacks").BroadcastValueUpdate(address, args)
# ===========================================================================

def BroadcastValueUpdate(address, args):
	"""Broadcast a parameter change from TouchDesigner to all web clients."""
	webServerDAT = op("webserver1")
	if not webServerDAT:
		print("[OSCQuery] BroadcastValueUpdate: cannot find webserver1 DAT")
		return
	update = json.dumps({
		"COMMAND": "VALUE_UPDATE",
		"ADDRESS": address,
		"ARGS": args
	})
	clients = _get_clients(webServerDAT)
	for c in clients:
		try:
			webServerDAT.webSocketSendText(c, update)
		except Exception:
			pass


# ===========================================================================
# Private helpers
# ===========================================================================

def _ok(response, contentType):
	response["statusCode"] = 200
	response["statusReason"] = "OK"
	response["content-type"] = contentType
	return response


def _notFound(response):
	response["statusCode"] = 404
	response["statusReason"] = "Not found"
	response["content-type"] = "text/html"
	return response


def _broadcastClientCount(webServerDAT):
	clients = _get_clients(webServerDAT)
	msg = json.dumps({
		"COMMAND": "CLIENT_COUNT",
		"CLIENTS": len(clients)
	})
	for c in clients:
		try:
			webServerDAT.webSocketSendText(c, msg)
		except Exception:
			pass


def _buildNotFoundPage():
	try:
		oscAddresses = parent().GetAllAddresses()
	except Exception:
		oscAddresses = []

	data = "<h1>Not Found</h1>"
	data += "No container or method was found at the supplied OSC address.<br><br>"
	data += "The following OSC addresses are available:<br><ul>"
	for a in oscAddresses:
		data += "<li>" + a + "</li>"
	data += "</ul>"
	return data
