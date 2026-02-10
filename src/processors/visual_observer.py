import asyncio
import time
from typing import Optional, List, Dict, Any
from loguru import logger
from pipecat.frames.frames import Frame, ImageRawFrame, TextFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
import base64
from PIL import Image
import io
import cv2
import numpy as np
try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    logger.warning("MediaPipe not available, using OpenCV for face detection")

class VisualObserver(FrameProcessor):
    """
    Observer that waits for UserImageRequestFrame, captures the next video frame,
    analyzes it with a vision model, and injects the description back into the context.
    Now includes face detection and display capabilities.
    """

    def __init__(
        self,
        vision_client,
        model="moondream",
        enable_display=False,
        enable_face_detection=True,
        webrtc_connection=None,
        tars_client=None
    ):
        super().__init__()
        self._vision_client = vision_client
        self._model = model
        self._waiting_for_image = False
        self._current_request = None
        self._last_analysis_time = 0
        self._cooldown = 2.0  # Min seconds between analyses
        self._enable_display = enable_display
        self._enable_face_detection = enable_face_detection
        self._webrtc_connection = webrtc_connection
        self._tars_client = None  # Deprecated: Display control via gRPC in robot mode
        self._display_window_name = "TARS Visual Observer"

        # Face detection setup
        self._face_detector = None
        if self._enable_face_detection:
            self._setup_face_detection()

        # Stats
        self._face_count = 0
        self._frames_processed = 0
        self._last_face_time = 0

    def _setup_face_detection(self):
        """Initialize face detection based on available libraries."""
        try:
            if MEDIAPIPE_AVAILABLE:
                logger.info("🎯 Initializing MediaPipe face detection")
                self._face_detector_type = "mediapipe"
                self._mp_face_detection = mp.solutions.face_detection
                self._mp_drawing = mp.solutions.drawing_utils
                self._face_detector = self._mp_face_detection.FaceDetection(
                    model_selection=0,  # 0 for short-range (< 2m), 1 for full-range
                    min_detection_confidence=0.5
                )
            else:
                # Fallback to OpenCV Haar Cascade
                logger.info("🎯 Initializing OpenCV Haar Cascade face detection")
                self._face_detector_type = "opencv"
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                self._face_detector = cv2.CascadeClassifier(cascade_path)
                if self._face_detector.empty():
                    logger.error("Failed to load Haar Cascade classifier")
                    self._face_detector = None
        except Exception as e:
            logger.error(f"Failed to initialize face detection: {e}")
            self._face_detector = None

    def detect_faces(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detect faces in the image.

        Args:
            image: numpy array in BGR format

        Returns:
            List of face dictionaries with bounding boxes and confidence
        """
        if not self._face_detector:
            return []

        faces = []
        try:
            if self._face_detector_type == "mediapipe":
                # Convert BGR to RGB for MediaPipe
                rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                results = self._face_detector.process(rgb_image)

                if results.detections:
                    h, w, _ = image.shape
                    for detection in results.detections:
                        bbox = detection.location_data.relative_bounding_box
                        faces.append({
                            'x': int(bbox.xmin * w),
                            'y': int(bbox.ymin * h),
                            'width': int(bbox.width * w),
                            'height': int(bbox.height * h),
                            'confidence': detection.score[0]
                        })
            else:  # opencv
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                detected_faces = self._face_detector.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(30, 30)
                )
                for (x, y, w, h) in detected_faces:
                    faces.append({
                        'x': x,
                        'y': y,
                        'width': w,
                        'height': h,
                        'confidence': 1.0  # OpenCV Haar doesn't provide confidence
                    })
        except Exception as e:
            logger.error(f"Error detecting faces: {e}")

        return faces

    def draw_faces(self, image: np.ndarray, faces: List[Dict[str, Any]]) -> np.ndarray:
        """
        Draw bounding boxes around detected faces.

        Args:
            image: numpy array in BGR format
            faces: List of face dictionaries from detect_faces()

        Returns:
            Image with faces drawn
        """
        annotated_image = image.copy()

        for face in faces:
            x, y, w, h = face['x'], face['y'], face['width'], face['height']
            confidence = face['confidence']

            # Draw rectangle
            cv2.rectangle(annotated_image, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # Draw confidence score
            label = f"Face: {confidence:.2f}"
            cv2.putText(
                annotated_image,
                label,
                (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2
            )

        # Draw face count
        cv2.putText(
            annotated_image,
            f"Faces: {len(faces)}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2
        )

        return annotated_image

    def display_frame(self, image: np.ndarray, faces: Optional[List[Dict[str, Any]]] = None):
        """
        Display the frame in a window with optional face annotations.

        Args:
            image: numpy array in BGR format
            faces: Optional list of detected faces to draw
        """
        if not self._enable_display:
            return

        try:
            display_image = image.copy()

            if faces:
                display_image = self.draw_faces(display_image, faces)

            cv2.imshow(self._display_window_name, display_image)
            cv2.waitKey(1)  # Required for window to update
        except Exception as e:
            logger.error(f"Error displaying frame: {e}")

    def send_display_event(self, faces: List[Dict[str, Any]], image_base64: Optional[str] = None):
        """
        Send display event to WebRTC connection with face detection results.

        Args:
            faces: List of detected faces
            image_base64: Optional base64-encoded image
        """
        if not self._webrtc_connection:
            return

        try:
            if self._webrtc_connection.is_connected():
                event_data = {
                    "type": "face_detection",
                    "status": "detected" if faces else "no_faces",
                    "face_count": len(faces),
                    "faces": faces,
                    "timestamp": time.time()
                }

                # Optionally include thumbnail
                if image_base64 and len(faces) > 0:
                    event_data["thumbnail"] = image_base64

                self._webrtc_connection.send_app_message(event_data)
        except Exception as e:
            logger.debug(f"Error sending display event: {e}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # 1. Handle Request from LLM (Check by class name to avoid import errors)
        # We check for "UserImageRequestFrame" (your custom frame) OR "VisionImageRequestFrame"
        if frame.__class__.__name__ in ["UserImageRequestFrame", "VisionImageRequestFrame"]:
            logger.info(f"👁️ Vision request received: {getattr(frame, 'context', 'No context')}")
            self._waiting_for_image = True
            self._current_request = frame
            # We don't yield this frame downstream; we consume it and act on it.
            return

        # 2. Handle Video Input (continuous face detection + optional vision analysis)
        if isinstance(frame, ImageRawFrame):
            self._frames_processed += 1

            # Process face detection on every frame (or throttled)
            if self._enable_face_detection and self._frames_processed % 5 == 0:
                # Run face detection in background
                asyncio.create_task(self._process_face_detection(frame))

            # Vision analysis only when requested
            if self._waiting_for_image:
                # Check cooldown
                if time.time() - self._last_analysis_time < self._cooldown:
                    await self.push_frame(frame, direction)
                    return

                logger.info("📸 Capturing frame for analysis...")
                self._waiting_for_image = False  # Reset flag immediately
                self._last_analysis_time = time.time()

                # Run analysis in background to avoid blocking audio pipeline
                asyncio.create_task(self._analyze_and_respond(frame))
                # Note: Still pass frame through for face detection

        # Pass all other frames through
        await self.push_frame(frame, direction)

    async def _process_face_detection(self, frame: ImageRawFrame):
        """Process face detection on video frame and send display events."""
        try:
            # Convert frame to numpy array
            image = Image.frombytes(frame.format, frame.size, frame.image)
            image_np = np.array(image)

            # Convert RGB to BGR for OpenCV
            if image_np.shape[2] == 3:
                image_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
            else:
                image_bgr = image_np

            # Get frame dimensions
            frame_height, frame_width = image_bgr.shape[:2]

            # Detect faces
            faces = self.detect_faces(image_bgr)

            if faces:
                self._face_count = len(faces)
                current_time = time.time()

                # Log only periodically to avoid spam
                if current_time - self._last_face_time > 5.0:
                    logger.info(f"👤 Detected {len(faces)} face(s)")
                    self._last_face_time = current_time

                # Get the largest/most prominent face
                primary_face = max(faces, key=lambda f: f['width'] * f['height'])

                # Calculate face center
                face_center_x = primary_face['x'] + primary_face['width'] // 2
                face_center_y = primary_face['y'] + primary_face['height'] // 2

                # Display the frame with face annotations
                self.display_frame(image_bgr, faces)

                # Send face position event to WebRTC frontend
                self.send_display_event(faces)

                # Optionally send face position to text frame for LLM context
                # This can be used for "user is looking at you" type feedback
                # Uncomment if you want the LLM to know about face position
                # face_text = f"[Face Detected]: Position ({face_center_x}, {face_center_y}), Size: {primary_face['width']}x{primary_face['height']}"
                # await self.push_frame(TextFrame(text=face_text), FrameDirection.UPSTREAM)
            else:
                # No faces detected
                if self._face_count > 0:
                    logger.debug("No faces detected")
                    self._face_count = 0
                    # Send "no face" event to WebRTC
                    self.send_display_event([])

                # Display frame without annotations
                self.display_frame(image_bgr)

        except Exception as e:
            logger.error(f"Error in face detection: {e}")

    async def _analyze_and_respond(self, frame: ImageRawFrame):
        """Analyze image and push result text frame downstream."""
        try:
            # Convert raw frame to base64
            image = Image.frombytes(frame.format, frame.size, frame.image)
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            prompt = "Describe this image briefly."
            
            # Try to extract prompt from the request context if available
            if self._current_request and hasattr(self._current_request, 'context'):
                 # Assuming context might be the question text
                 context = self._current_request.context
                 if context: 
                     prompt = f"{context} (Describe the image to answer this)"

            logger.info(f"🔍 Sending image to vision model ({self._model})...")
            
            try:
                response = await asyncio.wait_for(
                    self._vision_client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{img_str}"
                                        },
                                    },
                                ],
                            }
                        ],
                        max_tokens=100
                    ),
                    timeout=8.0  # 8 second timeout to prevent hanging
                )
                description = response.choices[0].message.content
                logger.info(f"✅ Vision analysis: {description}")

            except asyncio.TimeoutError:
                logger.warning("⚠️ Vision model timed out!")
                description = "I couldn't see clearly because the visual processing timed out."
            except Exception as e:
                logger.error(f"❌ Vision model error: {e}")
                description = "I had trouble processing the visual data."

            feedback_text = f"[Visual Observation]: {description}"
            
            # Push text frame to LLM
            await self.push_frame(TextFrame(text=feedback_text), FrameDirection.UPSTREAM)

        except Exception as e:
            logger.error(f"Error in vision pipeline: {e}")
            self._waiting_for_image = False