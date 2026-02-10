"""
Test script for local vs remote mode detection.
"""

from config import (
    detect_deployment_mode,
    get_robot_grpc_address,
    is_raspberry_pi,
    RPI_GRPC,
)
from services import tars_robot

print("=" * 60)
print("TARS Mode Detection Test")
print("=" * 60)

# Test 1: Raspberry Pi detection
print("\n1. Platform Detection:")
print(f"   Is Raspberry Pi: {is_raspberry_pi()}")

# Test 2: Deployment mode
print("\n2. Deployment Mode:")
mode = detect_deployment_mode()
print(f"   Mode: {mode}")

# Test 3: gRPC address selection
print("\n3. gRPC Address Selection:")
address = get_robot_grpc_address()
print(f"   Auto-detected address: {address}")
print(f"   Config address (RPI_GRPC): {RPI_GRPC}")

if mode == "local":
    expected = "localhost:50051"
else:
    expected = RPI_GRPC

if address == expected:
    print(f"   Status: OK (using {expected})")
else:
    print(f"   Status: ERROR (expected {expected}, got {address})")

# Test 4: Robot service SDK
print("\n4. Robot Service SDK:")
print(f"   SDK Available: {tars_robot.TARS_SDK_AVAILABLE}")

if tars_robot.TARS_SDK_AVAILABLE:
    print(f"   SDK Import: OK")
    client = tars_robot.get_robot_client(address=address)
    if client:
        print(f"   Client Address: {client.address}")
    else:
        print(f"   Client: None (SDK not available)")

print("\n" + "=" * 60)
print("Test Complete")
print("=" * 60)
