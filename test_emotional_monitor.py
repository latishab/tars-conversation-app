#!/usr/bin/env python3
"""
Test script for Emotional State Monitoring
Demonstrates real-time emotion/confusion detection
"""

import asyncio
import sys
from loguru import logger
from processors.emotional_monitor import EmotionalStateMonitor, EmotionalState

logger.remove(0)
logger.add(sys.stderr, level="INFO")


class MockVisionClient:
    """Mock vision client for testing"""

    def __init__(self, response_text: str = "The person looks focused and attentive."):
        self.response_text = response_text
        self.chat = self

    class Completions:
        def __init__(self, parent):
            self.parent = parent

        async def create(self, **kwargs):
            # Simulate API delay
            await asyncio.sleep(0.1)

            # Return mock response
            class MockResponse:
                def __init__(self, text):
                    self.choices = [
                        type('obj', (object,), {
                            'message': type('obj', (object,), {
                                'content': text
                            })()
                        })()
                    ]

            return MockResponse(self.parent.response_text)

    @property
    def completions(self):
        return self.Completions(self)


async def test_emotional_states():
    """Test different emotional state scenarios"""
    print("=" * 60)
    print("Testing Emotional State Monitoring")
    print("=" * 60)

    # Test 1: Focused state (no intervention)
    print("\n📊 Test 1: Focused state")
    client = MockVisionClient("The person appears focused and engaged.")
    state = EmotionalState(focused=True, confidence=0.8)
    print(f"   State: {state}")
    print(f"   Needs intervention: {state.needs_intervention()}")
    assert not state.needs_intervention(), "Focused state should not trigger intervention"

    # Test 2: Confused state (should intervene)
    print("\n📊 Test 2: Confused state")
    state = EmotionalState(confused=True, confidence=0.7)
    print(f"   State: {state}")
    print(f"   Needs intervention: {state.needs_intervention()}")
    assert state.needs_intervention(), "Confused state should trigger intervention"

    # Test 3: Hesitant state (should intervene)
    print("\n📊 Test 3: Hesitant state")
    state = EmotionalState(hesitant=True, confidence=0.6)
    print(f"   State: {state}")
    print(f"   Needs intervention: {state.needs_intervention()}")
    assert state.needs_intervention(), "Hesitant state should trigger intervention"

    # Test 4: Frustrated state (should intervene)
    print("\n📊 Test 4: Frustrated state")
    state = EmotionalState(frustrated=True, confidence=0.8)
    print(f"   State: {state}")
    print(f"   Needs intervention: {state.needs_intervention()}")
    assert state.needs_intervention(), "Frustrated state should trigger intervention"

    print("\n✅ All state tests passed!")


async def test_monitor_initialization():
    """Test monitor initialization and configuration"""
    print("\n" + "=" * 60)
    print("Testing Monitor Initialization")
    print("=" * 60)

    client = MockVisionClient()

    monitor = EmotionalStateMonitor(
        vision_client=client,
        sampling_interval=2.0,
        intervention_threshold=3,
        enabled=True,
    )

    print(f"\n✅ Monitor initialized successfully")
    print(f"   Enabled: True")
    print(f"   Sampling interval: 2.0s")
    print(f"   Intervention threshold: 3")

    # Test enable/disable
    monitor.disable()
    assert not monitor._enabled, "Monitor should be disabled"
    print(f"   Disabled successfully")

    monitor.enable()
    assert monitor._enabled, "Monitor should be enabled"
    print(f"   Enabled successfully")


async def test_state_summary():
    """Test state summary functionality"""
    print("\n" + "=" * 60)
    print("Testing State Summary")
    print("=" * 60)

    client = MockVisionClient()
    monitor = EmotionalStateMonitor(vision_client=client)

    # Simulate some state history
    monitor._state_history = [
        EmotionalState(focused=True),
        EmotionalState(confused=True),
        EmotionalState(confused=True),
        EmotionalState(focused=True),
        EmotionalState(hesitant=True),
    ]
    monitor._last_state = monitor._state_history[-1]

    summary = monitor.get_state_summary()
    print(f"\n📊 State Summary:")
    print(f"   Total samples: {summary['total_samples']}")
    print(f"   Confused ratio: {summary['confused_ratio']:.2%}")
    print(f"   Hesitant ratio: {summary['hesitant_ratio']:.2%}")
    print(f"   Focused ratio: {summary['focused_ratio']:.2%}")
    print(f"   Current state: {summary['current_state']}")

    assert summary['total_samples'] == 5
    assert summary['confused_ratio'] == 0.4  # 2/5
    assert summary['hesitant_ratio'] == 0.2  # 1/5
    assert summary['focused_ratio'] == 0.4  # 2/5

    print(f"\n✅ State summary test passed!")


async def main():
    """Run all tests"""
    try:
        await test_emotional_states()
        await test_monitor_initialization()
        await test_state_summary()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        print("\n💡 To use in production:")
        print("   1. Set EMOTIONAL_MONITORING_ENABLED=true in .env.local")
        print("   2. Adjust EMOTIONAL_SAMPLING_INTERVAL (default: 3.0s)")
        print("   3. Adjust EMOTIONAL_INTERVENTION_THRESHOLD (default: 2)")
        print("   4. Start the bot - it will automatically monitor emotions!")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
