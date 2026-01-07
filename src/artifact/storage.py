"""
Artifact storage interfaces and implementations.

This module provides abstract storage interfaces and concrete implementations
for storing and retrieving artifacts in different backends.
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import threading
import uuid

from .models import Artifact, ArtifactVersion, ArtifactQuery


class ArtifactStorage(ABC):
    """Abstract base class for artifact storage backends."""
    
    @abstractmethod
    def store_artifact(self, artifact: Artifact) -> str:
        """Store an artifact and return its ID."""
        pass
    
    @abstractmethod
    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieve an artifact by ID."""
        pass
    
    @abstractmethod
    def update_artifact(self, artifact: Artifact) -> bool:
        """Update an existing artifact."""
        pass
    
    @abstractmethod
    def delete_artifact(self, artifact_id: str) -> bool:
        """Delete an artifact by ID."""
        pass
    
    @abstractmethod
    def query_artifacts(self, query: ArtifactQuery) -> List[Artifact]:
        """Query artifacts based on criteria."""
        pass
    
    @abstractmethod
    def store_version(self, version: ArtifactVersion) -> str:
        """Store an artifact version."""
        pass
    
    @abstractmethod
    def get_versions(self, artifact_id: str) -> List[ArtifactVersion]:
        """Get all versions of an artifact."""
        pass
    
    @abstractmethod
    def get_version(self, version_id: str) -> Optional[ArtifactVersion]:
        """Get a specific version by ID."""
        pass


class MemoryArtifactStorage(ArtifactStorage):
    """In-memory implementation of artifact storage."""
    
    def __init__(self):
        self._artifacts: Dict[str, Artifact] = {}
        self._versions: Dict[str, ArtifactVersion] = {}
        self._artifact_versions: Dict[str, List[str]] = {}  # artifact_id -> version_ids
        self._lock = threading.RLock()
    
    def store_artifact(self, artifact: Artifact) -> str:
        """Store an artifact in memory."""
        with self._lock:
            if not artifact.id:
                artifact.id = str(uuid.uuid4())
            
            # Update timestamp
            artifact.updated_at = datetime.now()
            
            # Store the artifact
            self._artifacts[artifact.id] = artifact
            
            # Initialize version list if needed
            if artifact.id not in self._artifact_versions:
                self._artifact_versions[artifact.id] = []
            
            return artifact.id
    
    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieve an artifact from memory."""
        with self._lock:
            return self._artifacts.get(artifact_id)
    
    def update_artifact(self, artifact: Artifact) -> bool:
        """Update an existing artifact in memory."""
        with self._lock:
            if artifact.id not in self._artifacts:
                return False
            
            artifact.updated_at = datetime.now()
            self._artifacts[artifact.id] = artifact
            return True
    
    def delete_artifact(self, artifact_id: str) -> bool:
        """Delete an artifact from memory."""
        with self._lock:
            if artifact_id not in self._artifacts:
                return False
            
            # Remove artifact
            del self._artifacts[artifact_id]
            
            # Remove associated versions
            if artifact_id in self._artifact_versions:
                version_ids = self._artifact_versions[artifact_id]
                for version_id in version_ids:
                    self._versions.pop(version_id, None)
                del self._artifact_versions[artifact_id]
            
            return True
    
    def query_artifacts(self, query: ArtifactQuery) -> List[Artifact]:
        """Query artifacts in memory."""
        with self._lock:
            results = []
            
            for artifact in self._artifacts.values():
                if query.matches(artifact):
                    results.append(artifact)
            
            # Sort by creation date (newest first)
            results.sort(key=lambda a: a.created_at, reverse=True)
            
            # Apply pagination
            start = query.offset
            end = start + query.limit if query.limit else None
            
            return results[start:end]
    
    def store_version(self, version: ArtifactVersion) -> str:
        """Store an artifact version in memory."""
        with self._lock:
            if not version.version_id:
                version.version_id = str(uuid.uuid4())
            
            self._versions[version.version_id] = version
            
            # Add to artifact's version list
            if version.artifact_id not in self._artifact_versions:
                self._artifact_versions[version.artifact_id] = []
            
            if version.version_id not in self._artifact_versions[version.artifact_id]:
                self._artifact_versions[version.artifact_id].append(version.version_id)
            
            return version.version_id
    
    def get_versions(self, artifact_id: str) -> List[ArtifactVersion]:
        """Get all versions of an artifact from memory."""
        with self._lock:
            version_ids = self._artifact_versions.get(artifact_id, [])
            versions = [self._versions[vid] for vid in version_ids if vid in self._versions]
            
            # Sort by creation date (newest first)
            versions.sort(key=lambda v: v.created_at, reverse=True)
            
            return versions
    
    def get_version(self, version_id: str) -> Optional[ArtifactVersion]:
        """Get a specific version by ID from memory."""
        with self._lock:
            return self._versions.get(version_id)
    
    def clear(self):
        """Clear all stored data (useful for testing)."""
        with self._lock:
            self._artifacts.clear()
            self._versions.clear()
            self._artifact_versions.clear()


class FileSystemArtifactStorage(ArtifactStorage):
    """File system implementation of artifact storage."""
    
    def __init__(self, base_path: str = "artifacts"):
        self.base_path = Path(base_path)
        self.artifacts_path = self.base_path / "artifacts"
        self.versions_path = self.base_path / "versions"
        
        # Create directories if they don't exist
        self.artifacts_path.mkdir(parents=True, exist_ok=True)
        self.versions_path.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.RLock()
    
    def _get_artifact_file_path(self, artifact_id: str) -> Path:
        """Get the file path for an artifact."""
        return self.artifacts_path / f"{artifact_id}.json"
    
    def _get_version_file_path(self, version_id: str) -> Path:
        """Get the file path for a version."""
        return self.versions_path / f"{version_id}.json"
    
    def store_artifact(self, artifact: Artifact) -> str:
        """Store an artifact to file system."""
        with self._lock:
            if not artifact.id:
                artifact.id = str(uuid.uuid4())
            
            artifact.updated_at = datetime.now()
            
            file_path = self._get_artifact_file_path(artifact.id)
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(artifact.to_dict(), f, indent=2, ensure_ascii=False)
                return artifact.id
            except Exception as e:
                raise RuntimeError(f"Failed to store artifact {artifact.id}: {e}")
    
    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieve an artifact from file system."""
        with self._lock:
            file_path = self._get_artifact_file_path(artifact_id)
            
            if not file_path.exists():
                return None
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return Artifact.from_dict(data)
            except Exception as e:
                raise RuntimeError(f"Failed to load artifact {artifact_id}: {e}")
    
    def update_artifact(self, artifact: Artifact) -> bool:
        """Update an existing artifact in file system."""
        with self._lock:
            file_path = self._get_artifact_file_path(artifact.id)
            
            if not file_path.exists():
                return False
            
            artifact.updated_at = datetime.now()
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(artifact.to_dict(), f, indent=2, ensure_ascii=False)
                return True
            except Exception as e:
                raise RuntimeError(f"Failed to update artifact {artifact.id}: {e}")
    
    def delete_artifact(self, artifact_id: str) -> bool:
        """Delete an artifact from file system."""
        with self._lock:
            file_path = self._get_artifact_file_path(artifact_id)
            
            if not file_path.exists():
                return False
            
            try:
                file_path.unlink()
                
                # Also delete associated versions
                for version_file in self.versions_path.glob("*.json"):
                    try:
                        with open(version_file, 'r', encoding='utf-8') as f:
                            version_data = json.load(f)
                        if version_data.get('artifact_id') == artifact_id:
                            version_file.unlink()
                    except Exception:
                        continue  # Skip corrupted version files
                
                return True
            except Exception as e:
                raise RuntimeError(f"Failed to delete artifact {artifact_id}: {e}")
    
    def query_artifacts(self, query: ArtifactQuery) -> List[Artifact]:
        """Query artifacts in file system."""
        with self._lock:
            results = []
            
            for artifact_file in self.artifacts_path.glob("*.json"):
                try:
                    with open(artifact_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    artifact = Artifact.from_dict(data)
                    
                    if query.matches(artifact):
                        results.append(artifact)
                        
                except Exception:
                    continue  # Skip corrupted files
            
            # Sort by creation date (newest first)
            results.sort(key=lambda a: a.created_at, reverse=True)
            
            # Apply pagination
            start = query.offset
            end = start + query.limit if query.limit else None
            
            return results[start:end]
    
    def store_version(self, version: ArtifactVersion) -> str:
        """Store an artifact version to file system."""
        with self._lock:
            if not version.version_id:
                version.version_id = str(uuid.uuid4())
            
            file_path = self._get_version_file_path(version.version_id)
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(version.to_dict(), f, indent=2, ensure_ascii=False)
                return version.version_id
            except Exception as e:
                raise RuntimeError(f"Failed to store version {version.version_id}: {e}")
    
    def get_versions(self, artifact_id: str) -> List[ArtifactVersion]:
        """Get all versions of an artifact from file system."""
        with self._lock:
            versions = []
            
            for version_file in self.versions_path.glob("*.json"):
                try:
                    with open(version_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if data.get('artifact_id') == artifact_id:
                        version = ArtifactVersion.from_dict(data)
                        versions.append(version)
                        
                except Exception:
                    continue  # Skip corrupted files
            
            # Sort by creation date (newest first)
            versions.sort(key=lambda v: v.created_at, reverse=True)
            
            return versions
    
    def get_version(self, version_id: str) -> Optional[ArtifactVersion]:
        """Get a specific version by ID from file system."""
        with self._lock:
            file_path = self._get_version_file_path(version_id)
            
            if not file_path.exists():
                return None
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return ArtifactVersion.from_dict(data)
            except Exception as e:
                raise RuntimeError(f"Failed to load version {version_id}: {e}")