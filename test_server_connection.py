#!/usr/bin/env python3
"""
Simple script to test server connectivity from Raspberry Pi.
Run this to diagnose connection issues.
"""

import asyncio
import aiohttp
import sys

SERVER_IP = "172.28.133.106"  # Change this to your MacBook's IP
SERVER_PORT = 7860
SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"

async def test_connection():
    print(f"Testing connection to {SERVER_URL}")
    print(f"Server IP: {SERVER_IP}")
    print(f"Server Port: {SERVER_PORT}")
    print("-" * 50)
    
    # Test 1: Basic connectivity
    print("\n1. Testing basic connectivity...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SERVER_URL}/api/status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✓ Server is reachable!")
                    print(f"  Status: {data}")
                    return True
                else:
                    print(f"✗ Server returned status {response.status}")
                    return False
    except aiohttp.ClientConnectorError as e:
        print(f"✗ Cannot connect to server: {e}")
        print(f"\nTroubleshooting:")
        print(f"  1. Make sure server is running on MacBook:")
        print(f"     python3 pipecat_service.py --host 0.0.0.0 --port 7860")
        print(f"  2. Check if IP address is correct:")
        print(f"     On MacBook, run: ipconfig getifaddr en0")
        print(f"  3. Test network connectivity:")
        print(f"     ping {SERVER_IP}")
        print(f"  4. Check firewall on MacBook")
        return False
    except asyncio.TimeoutError:
        print(f"✗ Connection timeout")
        print(f"  Server may be unreachable or firewall is blocking")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        SERVER_IP = sys.argv[1]
        SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"
    
    result = asyncio.run(test_connection())
    sys.exit(0 if result else 1)

