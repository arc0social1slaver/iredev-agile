"""
Version management system for knowledge modules in iReDev framework.
Handles versioning, updates, and compatibility checking.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import semver
import logging

from .knowledge_manager import KnowledgeModule, KnowledgeType

logger = logging.getLogger(__name__)


class VersionCompatibility(Enum):
    """Version compatibility levels."""
    COMPATIBLE = "compatible"
    MINOR_INCOMPATIBLE = "minor_incompatible"
    MAJOR_INCOMPATIBLE = "major_incompatible"
    UNKNOWN = "unknown"


@dataclass
class VersionInfo:
    """Version information for a knowledge module."""
    version: str
    release_date: datetime
    changelog: str = ""
    breaking_changes: List[str] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)  # module_id -> version
    compatibility_notes: str = ""
    
    def is_valid_semver(self) -> bool:
        """Check if version follows semantic versioning."""
        try:
            semver.VersionInfo.parse(self.version)
            return True
        except ValueError:
            return False


@dataclass
class ModuleVersionHistory:
    """Version history for a knowledge module."""
    module_id: str
    current_version: str
    versions: Dict[str, VersionInfo] = field(default_factory=dict)
    
    def add_version(self, version_info: VersionInfo) -> None:
        """Add a new version to the history."""
        self.versions[version_info.version] = version_info
        
        # Update current version if this is newer
        if self._is_newer_version(version_info.version, self.current_version):
            self.current_version = version_info.version
    
    def _is_newer_version(self, version1: str, version2: str) -> bool:
        """Check if version1 is newer than version2."""
        try:
            v1 = semver.VersionInfo.parse(version1)
            v2 = semver.VersionInfo.parse(version2)
            return v1 > v2
        except ValueError:
            # Fallback to string comparison if not valid semver
            return version1 > version2


class KnowledgeVersionManager:
    """Manages versions of knowledge modules."""
    
    def __init__(self, base_path: str):
        """Initialize the version manager.
        
        Args:
            base_path: Base path for knowledge modules.
        """
        self.base_path = Path(base_path)
        self.versions_path = self.base_path / ".versions"
        self.versions_path.mkdir(exist_ok=True)
        
        # Version history storage
        self._version_histories: Dict[str, ModuleVersionHistory] = {}
        
        # Load existing version histories
        self._load_version_histories()
    
    def _load_version_histories(self) -> None:
        """Load version histories from storage."""
        version_file = self.versions_path / "versions.yaml"
        
        if version_file.exists():
            try:
                with open(version_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                
                for module_id, history_data in data.get("modules", {}).items():
                    history = ModuleVersionHistory(
                        module_id=module_id,
                        current_version=history_data.get("current_version", "1.0.0")
                    )
                    
                    for version, version_data in history_data.get("versions", {}).items():
                        version_info = VersionInfo(
                            version=version,
                            release_date=datetime.fromisoformat(version_data.get("release_date", datetime.now().isoformat())),
                            changelog=version_data.get("changelog", ""),
                            breaking_changes=version_data.get("breaking_changes", []),
                            dependencies=version_data.get("dependencies", {}),
                            compatibility_notes=version_data.get("compatibility_notes", "")
                        )
                        history.versions[version] = version_info
                    
                    self._version_histories[module_id] = history
                    
            except Exception as e:
                logger.error(f"Failed to load version histories: {str(e)}")
    
    def _save_version_histories(self) -> None:
        """Save version histories to storage."""
        version_file = self.versions_path / "versions.yaml"
        
        data = {
            "last_updated": datetime.now().isoformat(),
            "modules": {}
        }
        
        for module_id, history in self._version_histories.items():
            data["modules"][module_id] = {
                "current_version": history.current_version,
                "versions": {}
            }
            
            for version, version_info in history.versions.items():
                data["modules"][module_id]["versions"][version] = {
                    "release_date": version_info.release_date.isoformat(),
                    "changelog": version_info.changelog,
                    "breaking_changes": version_info.breaking_changes,
                    "dependencies": version_info.dependencies,
                    "compatibility_notes": version_info.compatibility_notes
                }
        
        try:
            with open(version_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save version histories: {str(e)}")
    
    def register_module_version(self, module: KnowledgeModule, changelog: str = "", breaking_changes: Optional[List[str]] = None) -> None:
        """Register a new version of a knowledge module.
        
        Args:
            module: Knowledge module to register.
            changelog: Changelog for this version.
            breaking_changes: List of breaking changes.
        """
        module_id = module.id
        version = module.version
        
        # Get or create version history
        if module_id not in self._version_histories:
            self._version_histories[module_id] = ModuleVersionHistory(
                module_id=module_id,
                current_version=version
            )
        
        history = self._version_histories[module_id]
        
        # Create version info
        version_info = VersionInfo(
            version=version,
            release_date=module.updated_at,
            changelog=changelog,
            breaking_changes=breaking_changes or [],
            dependencies={dep: "latest" for dep in module.dependencies},
            compatibility_notes=""
        )
        
        # Add to history
        history.add_version(version_info)
        
        # Save to storage
        self._save_version_histories()
        
        logger.info(f"Registered version {version} for module {module_id}")
    
    def get_module_version_history(self, module_id: str) -> Optional[ModuleVersionHistory]:
        """Get version history for a module.
        
        Args:
            module_id: ID of the module.
            
        Returns:
            Version history or None if not found.
        """
        return self._version_histories.get(module_id)
    
    def get_current_version(self, module_id: str) -> Optional[str]:
        """Get current version of a module.
        
        Args:
            module_id: ID of the module.
            
        Returns:
            Current version string or None if not found.
        """
        history = self._version_histories.get(module_id)
        return history.current_version if history else None
    
    def check_version_compatibility(self, module_id: str, required_version: str) -> VersionCompatibility:
        """Check if a required version is compatible with the current version.
        
        Args:
            module_id: ID of the module.
            required_version: Required version string.
            
        Returns:
            Version compatibility level.
        """
        current_version = self.get_current_version(module_id)
        if not current_version:
            return VersionCompatibility.UNKNOWN
        
        try:
            current = semver.VersionInfo.parse(current_version)
            required = semver.VersionInfo.parse(required_version)
            
            if current.major != required.major:
                return VersionCompatibility.MAJOR_INCOMPATIBLE
            elif current.minor < required.minor:
                return VersionCompatibility.MINOR_INCOMPATIBLE
            else:
                return VersionCompatibility.COMPATIBLE
                
        except ValueError:
            # Fallback to string comparison if not valid semver
            if current_version == required_version:
                return VersionCompatibility.COMPATIBLE
            else:
                return VersionCompatibility.UNKNOWN
    
    def get_available_versions(self, module_id: str) -> List[str]:
        """Get all available versions for a module.
        
        Args:
            module_id: ID of the module.
            
        Returns:
            List of available version strings.
        """
        history = self._version_histories.get(module_id)
        if not history:
            return []
        
        versions = list(history.versions.keys())
        
        # Sort versions (newest first)
        try:
            versions.sort(key=lambda v: semver.VersionInfo.parse(v), reverse=True)
        except ValueError:
            # Fallback to string sort if not valid semver
            versions.sort(reverse=True)
        
        return versions
    
    def get_version_info(self, module_id: str, version: str) -> Optional[VersionInfo]:
        """Get information about a specific version.
        
        Args:
            module_id: ID of the module.
            version: Version string.
            
        Returns:
            Version information or None if not found.
        """
        history = self._version_histories.get(module_id)
        if not history:
            return None
        
        return history.versions.get(version)
    
    def check_dependencies_compatibility(self, module_id: str, version: str) -> Dict[str, VersionCompatibility]:
        """Check compatibility of module dependencies.
        
        Args:
            module_id: ID of the module.
            version: Version of the module.
            
        Returns:
            Dictionary mapping dependency IDs to compatibility levels.
        """
        version_info = self.get_version_info(module_id, version)
        if not version_info:
            return {}
        
        compatibility = {}
        
        for dep_id, dep_version in version_info.dependencies.items():
            if dep_version == "latest":
                # Always compatible with latest
                compatibility[dep_id] = VersionCompatibility.COMPATIBLE
            else:
                compatibility[dep_id] = self.check_version_compatibility(dep_id, dep_version)
        
        return compatibility
    
    def suggest_version_update(self, module_id: str) -> Optional[Tuple[str, str]]:
        """Suggest a version update for a module.
        
        Args:
            module_id: ID of the module.
            
        Returns:
            Tuple of (current_version, suggested_version) or None.
        """
        history = self._version_histories.get(module_id)
        if not history:
            return None
        
        current_version = history.current_version
        
        try:
            current = semver.VersionInfo.parse(current_version)
            
            # Suggest patch version increment for minor updates
            suggested = f"{current.major}.{current.minor}.{current.patch + 1}"
            
            return (current_version, suggested)
            
        except ValueError:
            # Fallback for non-semver versions
            return (current_version, f"{current_version}.1")
    
    def validate_version_constraints(self, constraints: Dict[str, str]) -> List[str]:
        """Validate version constraints for multiple modules.
        
        Args:
            constraints: Dictionary mapping module IDs to version constraints.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        for module_id, constraint in constraints.items():
            if module_id not in self._version_histories:
                errors.append(f"Module {module_id} not found in version history")
                continue
            
            compatibility = self.check_version_compatibility(module_id, constraint)
            
            if compatibility == VersionCompatibility.MAJOR_INCOMPATIBLE:
                errors.append(f"Module {module_id} version constraint {constraint} is major incompatible")
            elif compatibility == VersionCompatibility.MINOR_INCOMPATIBLE:
                errors.append(f"Module {module_id} version constraint {constraint} is minor incompatible")
            elif compatibility == VersionCompatibility.UNKNOWN:
                errors.append(f"Module {module_id} version constraint {constraint} compatibility unknown")
        
        return errors
    
    def create_version_snapshot(self, snapshot_name: str) -> str:
        """Create a snapshot of current module versions.
        
        Args:
            snapshot_name: Name of the snapshot.
            
        Returns:
            Path to the snapshot file.
        """
        snapshot_data = {
            "name": snapshot_name,
            "created_at": datetime.now().isoformat(),
            "modules": {}
        }
        
        for module_id, history in self._version_histories.items():
            snapshot_data["modules"][module_id] = {
                "version": history.current_version,
                "checksum": ""  # Would be calculated from actual module content
            }
        
        snapshot_file = self.versions_path / f"snapshot_{snapshot_name}.yaml"
        
        try:
            with open(snapshot_file, 'w', encoding='utf-8') as f:
                yaml.dump(snapshot_data, f, default_flow_style=False, indent=2)
            
            logger.info(f"Created version snapshot: {snapshot_file}")
            return str(snapshot_file)
            
        except Exception as e:
            logger.error(f"Failed to create snapshot {snapshot_name}: {str(e)}")
            raise
    
    def restore_from_snapshot(self, snapshot_name: str) -> bool:
        """Restore module versions from a snapshot.
        
        Args:
            snapshot_name: Name of the snapshot to restore.
            
        Returns:
            True if successful, False otherwise.
        """
        snapshot_file = self.versions_path / f"snapshot_{snapshot_name}.yaml"
        
        if not snapshot_file.exists():
            logger.error(f"Snapshot file not found: {snapshot_file}")
            return False
        
        try:
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                snapshot_data = yaml.safe_load(f)
            
            # This would require actual module restoration logic
            # For now, just log what would be restored
            logger.info(f"Would restore {len(snapshot_data.get('modules', {}))} modules from snapshot {snapshot_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore from snapshot {snapshot_name}: {str(e)}")
            return False


class KnowledgeUpdateManager:
    """Manages updates to knowledge modules."""
    
    def __init__(self, version_manager: KnowledgeVersionManager):
        """Initialize the update manager.
        
        Args:
            version_manager: Version manager instance.
        """
        self.version_manager = version_manager
        self.update_queue: List[Dict[str, Any]] = []
    
    def check_for_updates(self, module_ids: Optional[List[str]] = None) -> Dict[str, str]:
        """Check for available updates for modules.
        
        Args:
            module_ids: Optional list of module IDs to check. If None, checks all.
            
        Returns:
            Dictionary mapping module IDs to available update versions.
        """
        updates = {}
        
        # This would typically check against a remote repository
        # For now, just return empty dict as placeholder
        logger.info("Checking for knowledge module updates...")
        
        return updates
    
    def schedule_update(self, module_id: str, target_version: str, auto_apply: bool = False) -> None:
        """Schedule an update for a module.
        
        Args:
            module_id: ID of the module to update.
            target_version: Target version to update to.
            auto_apply: Whether to apply the update automatically.
        """
        update_item = {
            "module_id": module_id,
            "target_version": target_version,
            "scheduled_at": datetime.now().isoformat(),
            "auto_apply": auto_apply,
            "status": "scheduled"
        }
        
        self.update_queue.append(update_item)
        logger.info(f"Scheduled update for {module_id} to version {target_version}")
    
    def apply_updates(self) -> List[str]:
        """Apply scheduled updates.
        
        Returns:
            List of successfully updated module IDs.
        """
        updated_modules = []
        
        for update_item in self.update_queue[:]:
            if update_item["status"] == "scheduled":
                try:
                    # This would contain actual update logic
                    module_id = update_item["module_id"]
                    target_version = update_item["target_version"]
                    
                    logger.info(f"Applying update for {module_id} to version {target_version}")
                    
                    # Mark as completed
                    update_item["status"] = "completed"
                    update_item["completed_at"] = datetime.now().isoformat()
                    
                    updated_modules.append(module_id)
                    
                except Exception as e:
                    logger.error(f"Failed to update {update_item['module_id']}: {str(e)}")
                    update_item["status"] = "failed"
                    update_item["error"] = str(e)
        
        # Remove completed updates
        self.update_queue = [item for item in self.update_queue if item["status"] not in ["completed", "failed"]]
        
        return updated_modules