"""
Dynamic loading and update system for knowledge modules in iReDev framework.
Handles hot-reloading, caching, and automatic updates.
"""

import os
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent
import logging

from .knowledge_manager import KnowledgeManager, KnowledgeModule, KnowledgeType
from .version_manager import KnowledgeVersionManager, KnowledgeUpdateManager

logger = logging.getLogger(__name__)


@dataclass
class LoaderConfig:
    """Configuration for the dynamic loader."""
    auto_reload: bool = True
    watch_filesystem: bool = True
    cache_ttl_minutes: int = 60
    max_cache_size: int = 100
    reload_debounce_seconds: float = 1.0
    update_check_interval_minutes: int = 60
    enable_hot_reload: bool = True


@dataclass
class CacheEntry:
    """Cache entry for a knowledge module."""
    module: KnowledgeModule
    loaded_at: datetime
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    file_mtime: float = 0.0
    
    def is_expired(self, ttl_minutes: int) -> bool:
        """Check if the cache entry is expired."""
        return datetime.now() - self.loaded_at > timedelta(minutes=ttl_minutes)
    
    def is_stale(self, file_path: str) -> bool:
        """Check if the cache entry is stale compared to file."""
        try:
            current_mtime = os.path.getmtime(file_path)
            return current_mtime > self.file_mtime
        except OSError:
            return True


class KnowledgeFileWatcher(FileSystemEventHandler):
    """File system watcher for knowledge modules."""
    
    def __init__(self, dynamic_loader: 'DynamicKnowledgeLoader'):
        """Initialize the file watcher.
        
        Args:
            dynamic_loader: Reference to the dynamic loader.
        """
        self.dynamic_loader = dynamic_loader
        self.debounce_timers: Dict[str, threading.Timer] = {}
        
    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory and self._is_knowledge_file(event.src_path):
            self._schedule_reload(event.src_path)
    
    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory and self._is_knowledge_file(event.src_path):
            self._schedule_reload(event.src_path)
    
    def on_deleted(self, event):
        """Handle file deletion events."""
        if not event.is_directory and self._is_knowledge_file(event.src_path):
            self.dynamic_loader._handle_file_deleted(event.src_path)
    
    def _is_knowledge_file(self, file_path: str) -> bool:
        """Check if a file is a knowledge module file."""
        path = Path(file_path)
        return path.suffix.lower() in ['.yaml', '.yml', '.json'] and not path.name.startswith('.')
    
    def _schedule_reload(self, file_path: str):
        """Schedule a reload with debouncing."""
        # Cancel existing timer for this file
        if file_path in self.debounce_timers:
            self.debounce_timers[file_path].cancel()
        
        # Schedule new reload
        timer = threading.Timer(
            self.dynamic_loader.config.reload_debounce_seconds,
            self.dynamic_loader._handle_file_changed,
            args=[file_path]
        )
        timer.start()
        self.debounce_timers[file_path] = timer


class DynamicKnowledgeLoader:
    """Dynamic loader for knowledge modules with caching and hot-reload capabilities."""
    
    def __init__(self, knowledge_manager: KnowledgeManager, config: LoaderConfig):
        """Initialize the dynamic loader.
        
        Args:
            knowledge_manager: Knowledge manager instance.
            config: Loader configuration.
        """
        self.knowledge_manager = knowledge_manager
        self.config = config
        
        # Cache management
        self._cache: Dict[str, CacheEntry] = {}
        self._cache_lock = threading.RLock()
        
        # File watching
        self._observer: Optional[Observer] = None
        self._file_watcher: Optional[KnowledgeFileWatcher] = None
        
        # Update management
        self.version_manager = KnowledgeVersionManager(str(knowledge_manager.base_path))
        self.update_manager = KnowledgeUpdateManager(self.version_manager)
        
        # Callbacks
        self._reload_callbacks: List[Callable[[str, KnowledgeModule], None]] = []
        self._update_callbacks: List[Callable[[str, str], None]] = []
        
        # Background tasks
        self._update_check_timer: Optional[threading.Timer] = None
        self._cache_cleanup_timer: Optional[threading.Timer] = None
        
        # Initialize
        self._start_background_tasks()
        if config.watch_filesystem:
            self._start_file_watching()
    
    def _start_background_tasks(self):
        """Start background tasks for cache cleanup and update checking."""
        if self.config.cache_ttl_minutes > 0:
            self._schedule_cache_cleanup()
        
        if self.config.update_check_interval_minutes > 0:
            self._schedule_update_check()
    
    def _start_file_watching(self):
        """Start file system watching for automatic reloading."""
        try:
            self._observer = Observer()
            self._file_watcher = KnowledgeFileWatcher(self)
            
            # Watch all knowledge type directories
            for knowledge_type, type_path in self.knowledge_manager._type_paths.items():
                if type_path.exists():
                    self._observer.schedule(
                        self._file_watcher,
                        str(type_path),
                        recursive=True
                    )
                    logger.info(f"Watching {knowledge_type.value} directory: {type_path}")
            
            self._observer.start()
            logger.info("File system watching started")
            
        except Exception as e:
            logger.error(f"Failed to start file system watching: {str(e)}")
    
    def _schedule_cache_cleanup(self):
        """Schedule periodic cache cleanup."""
        def cleanup():
            self._cleanup_cache()
            self._schedule_cache_cleanup()  # Reschedule
        
        self._cache_cleanup_timer = threading.Timer(
            self.config.cache_ttl_minutes * 60,
            cleanup
        )
        self._cache_cleanup_timer.start()
    
    def _schedule_update_check(self):
        """Schedule periodic update checking."""
        def check_updates():
            self._check_for_updates()
            self._schedule_update_check()  # Reschedule
        
        self._update_check_timer = threading.Timer(
            self.config.update_check_interval_minutes * 60,
            check_updates
        )
        self._update_check_timer.start()
    
    def load_module(self, module_id: str, force_reload: bool = False) -> Optional[KnowledgeModule]:
        """Load a knowledge module with caching and dynamic updates.
        
        Args:
            module_id: ID of the module to load.
            force_reload: Force reload even if cached.
            
        Returns:
            Loaded knowledge module or None if not found.
        """
        with self._cache_lock:
            # Check cache first
            if not force_reload and module_id in self._cache:
                cache_entry = self._cache[module_id]
                
                # Check if cache is still valid
                if not cache_entry.is_expired(self.config.cache_ttl_minutes):
                    # Check if file has been modified
                    module_config = self.knowledge_manager._module_configs.get(module_id)
                    if module_config and not cache_entry.is_stale(module_config.file_path):
                        # Update access statistics
                        cache_entry.access_count += 1
                        cache_entry.last_accessed = datetime.now()
                        
                        logger.debug(f"Loaded module {module_id} from cache")
                        return cache_entry.module
            
            # Load from knowledge manager
            module = self.knowledge_manager.load_module(module_id, force_reload)
            
            if module:
                # Cache the module
                self._cache_module(module)
                
                # Trigger reload callbacks
                for callback in self._reload_callbacks:
                    try:
                        callback(module_id, module)
                    except Exception as e:
                        logger.error(f"Error in reload callback for {module_id}: {str(e)}")
            
            return module
    
    def _cache_module(self, module: KnowledgeModule):
        """Cache a knowledge module.
        
        Args:
            module: Module to cache.
        """
        module_config = self.knowledge_manager._module_configs.get(module.id)
        file_mtime = 0.0
        
        if module_config:
            try:
                file_mtime = os.path.getmtime(module_config.file_path)
            except OSError:
                pass
        
        cache_entry = CacheEntry(
            module=module,
            loaded_at=datetime.now(),
            file_mtime=file_mtime
        )
        
        self._cache[module.id] = cache_entry
        
        # Enforce cache size limit
        if len(self._cache) > self.config.max_cache_size:
            self._evict_least_used()
    
    def _evict_least_used(self):
        """Evict least recently used cache entries."""
        # Sort by last accessed time and access count
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: (x[1].last_accessed, x[1].access_count)
        )
        
        # Remove oldest entries until under limit
        while len(self._cache) > self.config.max_cache_size * 0.8:  # Remove to 80% of limit
            module_id, _ = sorted_entries.pop(0)
            del self._cache[module_id]
            logger.debug(f"Evicted module {module_id} from cache")
    
    def _cleanup_cache(self):
        """Clean up expired cache entries."""
        with self._cache_lock:
            expired_modules = []
            
            for module_id, cache_entry in self._cache.items():
                if cache_entry.is_expired(self.config.cache_ttl_minutes):
                    expired_modules.append(module_id)
            
            for module_id in expired_modules:
                del self._cache[module_id]
                logger.debug(f"Removed expired cache entry for {module_id}")
            
            if expired_modules:
                logger.info(f"Cleaned up {len(expired_modules)} expired cache entries")
    
    def _handle_file_changed(self, file_path: str):
        """Handle file change events.
        
        Args:
            file_path: Path to the changed file.
        """
        logger.info(f"Knowledge file changed: {file_path}")
        
        # Find affected modules
        affected_modules = self._find_modules_by_file_path(file_path)
        
        for module_id in affected_modules:
            if self.config.enable_hot_reload:
                # Reload the module
                logger.info(f"Hot-reloading module: {module_id}")
                self.load_module(module_id, force_reload=True)
            else:
                # Just invalidate cache
                with self._cache_lock:
                    if module_id in self._cache:
                        del self._cache[module_id]
                        logger.info(f"Invalidated cache for module: {module_id}")
    
    def _handle_file_deleted(self, file_path: str):
        """Handle file deletion events.
        
        Args:
            file_path: Path to the deleted file.
        """
        logger.warning(f"Knowledge file deleted: {file_path}")
        
        # Find affected modules and remove from cache
        affected_modules = self._find_modules_by_file_path(file_path)
        
        with self._cache_lock:
            for module_id in affected_modules:
                if module_id in self._cache:
                    del self._cache[module_id]
                    logger.info(f"Removed deleted module {module_id} from cache")
    
    def _find_modules_by_file_path(self, file_path: str) -> List[str]:
        """Find modules that use a specific file path.
        
        Args:
            file_path: File path to search for.
            
        Returns:
            List of module IDs that use the file.
        """
        affected_modules = []
        
        for module_id, config in self.knowledge_manager._module_configs.items():
            if os.path.abspath(config.file_path) == os.path.abspath(file_path):
                affected_modules.append(module_id)
        
        return affected_modules
    
    def _check_for_updates(self):
        """Check for available updates to knowledge modules."""
        try:
            logger.debug("Checking for knowledge module updates...")
            
            # Get available updates
            updates = self.update_manager.check_for_updates()
            
            if updates:
                logger.info(f"Found {len(updates)} available updates")
                
                # Trigger update callbacks
                for module_id, version in updates.items():
                    for callback in self._update_callbacks:
                        try:
                            callback(module_id, version)
                        except Exception as e:
                            logger.error(f"Error in update callback for {module_id}: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error checking for updates: {str(e)}")
    
    def add_reload_callback(self, callback: Callable[[str, KnowledgeModule], None]):
        """Add a callback for module reload events.
        
        Args:
            callback: Callback function that takes (module_id, module).
        """
        self._reload_callbacks.append(callback)
    
    def add_update_callback(self, callback: Callable[[str, str], None]):
        """Add a callback for update availability events.
        
        Args:
            callback: Callback function that takes (module_id, version).
        """
        self._update_callbacks.append(callback)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics.
        """
        with self._cache_lock:
            total_access_count = sum(entry.access_count for entry in self._cache.values())
            
            return {
                "cache_size": len(self._cache),
                "max_cache_size": self.config.max_cache_size,
                "total_access_count": total_access_count,
                "cache_hit_rate": 0.0,  # Would need to track misses to calculate
                "oldest_entry": min(
                    (entry.loaded_at for entry in self._cache.values()),
                    default=datetime.now()
                ).isoformat() if self._cache else None,
                "most_accessed_module": max(
                    self._cache.items(),
                    key=lambda x: x[1].access_count,
                    default=(None, None)
                )[0] if self._cache else None
            }
    
    def clear_cache(self):
        """Clear all cached modules."""
        with self._cache_lock:
            cache_size = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared {cache_size} modules from cache")
    
    def preload_modules(self, module_ids: List[str]):
        """Preload a list of modules into cache.
        
        Args:
            module_ids: List of module IDs to preload.
        """
        logger.info(f"Preloading {len(module_ids)} modules")
        
        for module_id in module_ids:
            try:
                self.load_module(module_id)
            except Exception as e:
                logger.error(f"Failed to preload module {module_id}: {str(e)}")
    
    def shutdown(self):
        """Shutdown the dynamic loader and cleanup resources."""
        logger.info("Shutting down dynamic knowledge loader")
        
        # Stop file watching
        if self._observer:
            self._observer.stop()
            self._observer.join()
        
        # Cancel timers
        if self._update_check_timer:
            self._update_check_timer.cancel()
        
        if self._cache_cleanup_timer:
            self._cache_cleanup_timer.cancel()
        
        # Clear cache
        self.clear_cache()
        
        logger.info("Dynamic knowledge loader shutdown complete")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.shutdown()