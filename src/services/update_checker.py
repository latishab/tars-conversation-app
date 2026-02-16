"""
TARS Update Checker Service

Checks daemon version on connection and notifies user of available updates.
Uses gRPC GetVersion and CheckUpdate endpoints.
"""

import time
from typing import Optional, Callable, Dict, Any
from loguru import logger

# Client version for compatibility checking
CLIENT_VERSION = "0.2.0"


class TarsUpdateChecker:
    """
    Checks TARS daemon version and available updates.

    Usage:
        checker = TarsUpdateChecker(robot_client)
        checker.on_update_available(lambda info: print(f"Update: {info}"))
        await checker.check_on_connect()
    """

    def __init__(
        self,
        robot_client,
        cache_duration: int = 3600,
        check_pypi: bool = True
    ):
        """
        Initialize update checker.

        Args:
            robot_client: TarsClient instance
            cache_duration: Seconds to cache version check results
            check_pypi: Whether to check PyPI for updates
        """
        self.client = robot_client
        self.cache_duration = cache_duration
        self.check_pypi = check_pypi

        self._last_check: Optional[float] = None
        self._cached_result: Optional[Dict[str, Any]] = None
        self._update_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def on_update_available(self, callback: Callable[[Dict[str, Any]], None]):
        """Register callback for when update is available."""
        self._update_callback = callback

    async def check_on_connect(self) -> Optional[Dict[str, Any]]:
        """
        Check version on connection.

        Returns cached result if within cache_duration.
        Logs appropriate messages and triggers callbacks.

        Returns:
            Dict with version and update info, or None on error
        """
        # Check cache
        if self._cached_result and self._last_check:
            if time.time() - self._last_check < self.cache_duration:
                return self._cached_result

        try:
            result = await self._check_version()
            self._cached_result = result
            self._last_check = time.time()

            self._log_version_info(result)

            if result.get("update_available") and self._update_callback:
                self._update_callback(result)

            return result

        except Exception as e:
            logger.warning(f"Version check failed: {e}")
            return None

    async def _check_version(self) -> Dict[str, Any]:
        """Perform version check via gRPC."""
        if self.client is None:
            raise RuntimeError("Robot client not available")

        # Get version info
        version_info = self.client.get_version()

        result = {
            "daemon_version": version_info.version,
            "git_commit": version_info.git_commit,
            "build_date": version_info.build_date,
            "python_version": version_info.python_version,
            "platform": version_info.platform,
            "minimum_client": version_info.minimum_client,
            "client_version": CLIENT_VERSION,
            "update_available": False,
            "latest_version": version_info.version,
            "severity": "none",
        }

        # Check compatibility
        if not self._is_client_compatible(version_info.minimum_client):
            result["client_outdated"] = True
            logger.error(
                f"Client version {CLIENT_VERSION} is below minimum required "
                f"{version_info.minimum_client}. Update required."
            )

        # Check for updates if enabled
        if self.check_pypi:
            try:
                update_info = self.client.check_update()
                result.update({
                    "update_available": update_info.update_available,
                    "latest_version": update_info.latest_version,
                    "severity": update_info.severity,
                    "release_notes": update_info.release_notes,
                    "pypi_url": update_info.pypi_url,
                    "github_url": update_info.github_url,
                })
            except Exception as e:
                logger.debug(f"Update check failed: {e}")

        return result

    def _is_client_compatible(self, minimum_version: str) -> bool:
        """Check if client version meets minimum requirement."""
        if not minimum_version:
            return True

        try:
            def parse_version(v):
                parts = v.split(".")
                return tuple(int(p) for p in parts[:3])

            client = parse_version(CLIENT_VERSION)
            minimum = parse_version(minimum_version)
            return client >= minimum
        except (ValueError, IndexError):
            return True

    def _log_version_info(self, result: Dict[str, Any]):
        """Log version information."""
        daemon_version = result.get("daemon_version", "unknown")
        git_commit = result.get("git_commit", "")

        version_str = daemon_version
        if git_commit:
            version_str += f" ({git_commit})"

        if result.get("update_available"):
            latest = result.get("latest_version", "")
            severity = result.get("severity", "optional")

            if severity == "required":
                logger.error("=" * 50)
                logger.error(f"REQUIRED UPDATE: {daemon_version} -> {latest}")
                logger.error("Run: pip install --upgrade tars-sdk")
                logger.error("=" * 50)
            elif severity == "recommended":
                logger.warning("=" * 50)
                logger.warning(f"Update available: {daemon_version} -> {latest}")
                logger.warning("Run: pip install --upgrade tars-sdk")
                logger.warning("=" * 50)
            else:
                logger.info(f"Update available: {daemon_version} -> {latest}")
                logger.info("Run: pip install --upgrade tars-sdk")
        else:
            logger.info(f"TARS daemon is up to date (v{version_str})")

        if result.get("client_outdated"):
            logger.error("Client version is outdated. Please update tars-omni.")


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two semantic versions.
    Returns: -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
    """
    def parse_version(v):
        parts = v.split(".")
        return tuple(int(p) for p in parts[:3])

    try:
        p1 = parse_version(v1)
        p2 = parse_version(v2)
        if p1 < p2:
            return -1
        elif p1 > p2:
            return 1
        return 0
    except (ValueError, IndexError):
        return 0
