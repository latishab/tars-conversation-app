# Running Pipecat Server on MacBook for Raspberry Pi Client

This guide shows you how to run the Pipecat server on your MacBook so your Raspberry Pi can connect to it.

## Step 1: Find Your MacBook's IP Address

First, find your MacBook's local IP address on your network:

```bash
# Method 1: Using ifconfig
ifconfig | grep "inet " | grep -v 127.0.0.1

# Method 2: Using ipconfig (simpler)
ipconfig getifaddr en0    # For Wi-Fi
ipconfig getifaddr en1    # For Ethernet (if connected)

# Method 3: System Settings
# Go to: System Settings > Network > Wi-Fi/Ethernet
# Look for "IP Address"
```

You'll get something like `192.168.1.100` or `10.0.0.50` - **save this IP address!**

## Step 2: Start the Server on MacBook

Open a terminal on your MacBook and navigate to the project directory:

```bash
cd /Users/mac/Desktop/tars-omni
```

Start the server with `--host 0.0.0.0` to make it accessible from other devices:

```bash
python3 pipecat_service.py --host 0.0.0.0 --port 7860
```

**Important:** Using `0.0.0.0` instead of `localhost` makes the server accessible from other devices on your network.

You should see output like:
```
INFO: Starting Pipecat service on http://0.0.0.0:7860...
INFO: Make sure SPEECHMATICS_API_KEY, ELEVENLABS_API_KEY, and QWEN_API_KEY are set
```

## Step 3: Verify Server is Running

In another terminal, test that the server is accessible:

```bash
# Test from MacBook (should work)
curl http://localhost:7860/api/status

# Test with your IP address (replace with your actual IP)
curl http://192.168.1.100:7860/api/status
```

Both should return a JSON response with status information.

## Step 4: Configure Firewall (if needed)

If your Raspberry Pi can't connect, you may need to allow incoming connections on port 7860:

```bash
# Check if firewall is blocking (macOS)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate

# Allow Python through firewall (if needed)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/python3
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp /usr/local/bin/python3
```

Or use System Settings:
1. Go to **System Settings > Network > Firewall**
2. Click **Options**
3. Make sure Python is allowed, or add port 7860

## Step 5: Run Client on Raspberry Pi

On your Raspberry Pi, run the client with your MacBook's IP address:

```bash
# Replace 192.168.1.100 with your MacBook's actual IP address
python3 raspberry_pi_client.py --server http://192.168.1.100:7860
```

## Troubleshooting

### Server not accessible from Raspberry Pi

1. **Check both devices are on the same network:**
   ```bash
   # On MacBook
   ifconfig | grep "inet "
   
   # On Raspberry Pi
   hostname -I
   ```
   Both should show IPs in the same range (e.g., both start with `192.168.1.`)

2. **Test connectivity:**
   ```bash
   # On Raspberry Pi, ping your MacBook
   ping 192.168.1.100
   ```

3. **Check server is listening on 0.0.0.0:**
   ```bash
   # On MacBook
   netstat -an | grep 7860
   ```
   Should show `*.7860` or `0.0.0.0:7860`, not `127.0.0.1:7860`

### Connection refused errors

- Make sure server is running with `--host 0.0.0.0`
- Check firewall settings
- Verify port 7860 is not blocked

### WebRTC connection fails

- WebRTC requires STUN/TURN servers for NAT traversal
- The client uses Google's STUN server by default
- If behind strict NAT, you may need a TURN server

## Quick Reference

**On MacBook:**
```bash
# 1. Find IP address
ipconfig getifaddr en0

# 2. Start server
python3 pipecat_service.py --host 0.0.0.0 --port 7860
```

**On Raspberry Pi:**
```bash
# Replace with your MacBook's IP
python3 raspberry_pi_client.py --server http://YOUR_MACBOOK_IP:7860
```

## Alternative: Using Environment Variable

You can also set the host in your `.env.local` file:

```env
PIPECAT_HOST=0.0.0.0
PIPECAT_PORT=7860
```

Then just run:
```bash
python3 pipecat_service.py
```

But using `--host 0.0.0.0` in the command is clearer and doesn't require editing config files.

