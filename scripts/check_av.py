import av

print(f"AV Version: {av.__version__}")

# Check for codecs in the available set
codecs = set(av.codecs_available)
print(f"VP8 in list: {'vp8' in codecs}")
print(f"H264 in list: {'h264' in codecs}")

print("-" * 20)

# 1. Test VP8 (The one causing your crash)
try:
    c = av.Codec('vp8', 'r')
    print("✓ VP8 Decoder instantiated successfully")
except Exception as e:
    print(f"X VP8 Decoder FAILED to instantiate: {e}")

# 2. Test H264 (The alternative we want to force)
try:
    c = av.Codec('h264', 'r')
    print("✓ H264 Decoder instantiated successfully")
except Exception as e:
    print(f"X H264 Decoder FAILED to instantiate: {e}")