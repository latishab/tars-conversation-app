from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMTextFrame,
    LLMFullResponseStartFrame,
    Frame,
    InputAudioRawFrame,
    StartFrame,
    EndFrame,
    CancelFrame,
    TTSTextFrame
)
from loguru import logger
import json
import re


class InputAudioFilter(FrameProcessor):
    """
    Dedicated filter to block InputAudioRawFrame from reaching TTS service.
    These frames should only go upstream (to STT), never downstream (to TTS).
    """
    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)
        
        # block Audio going Downstream
        if isinstance(frame, InputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            return
        await self.push_frame(frame, direction)

class ReasoningLeakFilter(FrameProcessor):
    """
    Strips reasoning artifacts and markdown formatting from LLM text tokens
    before they reach TTS. Handles <think> blocks (stateful), markdown inline
    formatting, and leading ellipsis tokens.
    """
    _MD_RE = re.compile(r'\*{1,3}|_{1,2}|`+')
    _LEAD_ELLIPSIS_RE = re.compile(r'^[\s…\.]+')

    def __init__(self):
        super().__init__()
        self._in_think = False
        self._think_buf = ""
        self._collecting = False

    def _reset(self):
        self._in_think = False
        self._think_buf = ""
        self._collecting = False

    def _strip_token(self, text: str) -> str:
        """
        Statefully strips <think>...</think> content, then applies
        regex-based markdown and ellipsis stripping.
        """
        output = []
        for ch in text:
            if self._in_think:
                self._think_buf += ch
                if self._think_buf.endswith("</think>"):
                    self._in_think = False
                    self._think_buf = ""
            else:
                self._think_buf += ch
                if self._think_buf == "<think>":
                    self._in_think = True
                    self._think_buf = ""
                elif not "<think>".startswith(self._think_buf):
                    output.extend(self._think_buf)
                    self._think_buf = ""
                # else: keep buffering potential <think> prefix

        # Flush think_buf if we didn't enter a think block
        if self._think_buf and not self._in_think:
            output.extend(self._think_buf)
            self._think_buf = ""

        result = "".join(output)
        result = self._MD_RE.sub("", result)
        result = self._LEAD_ELLIPSIS_RE.sub("", result)
        return result

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            self._reset()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._reset()
            self._collecting = True
            await self.push_frame(frame, direction)

        elif isinstance(frame, LLMTextFrame) and self._collecting:
            cleaned = self._strip_token(frame.text)
            if cleaned:
                await self.push_frame(LLMTextFrame(text=cleaned), direction)

        elif isinstance(frame, LLMFullResponseEndFrame):
            self._collecting = False
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)


class SilenceFilter(FrameProcessor):
    """
    Intercepts LLM responses. If response is {"action": "silence"}, drops it.
    Also strips [functionName({...})] tool-call annotations that the LLM
    occasionally leaks into its text stream.
    """
    def __init__(self):
        super().__init__()
        self.current_response_text = ""
        self.is_collecting = False
        self._annot_buf = ""   # chars buffered inside a potential [func(...)]
        self._in_annot = False

    def _process_text_token(self, text: str) -> str:
        """Strip [funcName({...})] annotations from a streaming text token."""
        output = []
        for ch in text:
            if not self._in_annot:
                if ch == '[':
                    self._in_annot = True
                    self._annot_buf = '['
                else:
                    output.append(ch)
            else:
                self._annot_buf += ch
                if ch == ']':
                    # Only emit if it doesn't look like a tool-call annotation
                    if not re.match(r'\[[a-zA-Z_]+\s*\(', self._annot_buf):
                        output.extend(self._annot_buf)
                    self._annot_buf = ""
                    self._in_annot = False
        return ''.join(output)

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            self.current_response_text = ""
            self.is_collecting = False
            self._annot_buf = ""
            self._in_annot = False
            await self.push_frame(frame, direction)
            return

        # Start collecting text
        if isinstance(frame, LLMFullResponseStartFrame):
            self.current_response_text = ""
            self.is_collecting = True
            self._annot_buf = ""
            self._in_annot = False
            await self.push_frame(frame, direction)

        # Accumulate and filter text tokens
        elif isinstance(frame, LLMTextFrame) and self.is_collecting:
            self.current_response_text += frame.text
            filtered = self._process_text_token(frame.text)
            if filtered:
                await self.push_frame(LLMTextFrame(text=filtered), direction)
            
        # Check the full response
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self.is_collecting:
                text = self.current_response_text.strip()
                try:
                    # Check for silence JSON
                    if "action" in text and "silence" in text:
                        clean_json = text.replace("```json", "").replace("```", "").strip()
                        data = json.loads(clean_json)
                        if data.get("action") == "silence":
                            logger.info("SilenceFilter: Suppressing silent response.")
                            self.is_collecting = False
                            return # Drop the EndFrame (silence the turn)
                except:
                    pass
                self.is_collecting = False
            await self.push_frame(frame, direction)
            
        # Pass everything else (like Audio or System messages)
        else:
            await self.push_frame(frame, direction)

