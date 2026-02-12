"""Provenance metadata generation for fathom bundles."""

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List


def get_git_info() -> Optional[Dict[str, Any]]:
    """Get git commit and dirty status.
    
    Returns:
        Dict with 'commit' and 'dirty' keys, or None if not a git repo
    """
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        
        status = subprocess.check_output(
            ['git', 'status', '--porcelain'],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        
        return {
            'commit': commit,
            'dirty': bool(status)
        }
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_runtime_info() -> Dict[str, str]:
    """Get runtime environment information.
    
    Returns:
        Dict with 'os', 'arch', 'python' keys
    """
    return {
        'os': platform.system(),
        'arch': platform.machine(),
        'python': platform.python_version()
    }


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of file.
    
    Args:
        path: Path to file
        
    Returns:
        Hex string of SHA-256 hash
    """
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def write_provenance(path: Path, provenance: dict) -> None:
    """Write provenance dict to JSON file.
    
    Args:
        path: Output file path
        provenance: Provenance dict
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False)


class ProvenanceBuilder:
    """Provenance metadata builder.
    
    Incrementally constructs provenance.json metadata.
    
    Usage:
        pb = ProvenanceBuilder(
            bundle_id="20260212-0915--a3f91c",
            folder_name="bndl_...",
            extended=False
        )
        pb.set_tool_info(name="fathom", version="1.0.0")
        pb.add_task(
            task_id="sillok-search-001",
            db="sillok",
            mode="search",
            raw_request={...},
            normalized_request={...}
        )
        pb.update_task_stats("sillok-search-001", selected=412, succeeded=409, failed=3)
        pb.set_outputs(
            articles_path="articles.jsonl",
            articles_count=409,
            failed_path="failed.jsonl",
            failed_count=3
        )
        prov = pb.build()
    """
    
    def __init__(
        self,
        bundle_id: str,
        folder_name: str,
        extended: bool = False
    ):
        """Initialize provenance builder.
        
        Args:
            bundle_id: Bundle ID (timestamp--id6 part)
            folder_name: Full bundle folder name
            extended: Include extended provenance fields
        """
        self.bundle_id = bundle_id
        self.folder_name = folder_name
        self.extended = extended
        
        self.tool_info: Dict[str, Any] = {}
        self.tasks: List[Dict[str, Any]] = []
        self.outputs: Dict[str, Any] = {'files': {}}
        self.cli_argv: Optional[List[str]] = None
        self.resume_info: Optional[Dict[str, Any]] = None
        self.notes: Optional[str] = None
        
        self._task_index: Dict[str, int] = {}
    
    def set_tool_info(self, name: str, version: str) -> None:
        """Set tool information.
        
        Args:
            name: Tool name
            version: Tool version
        """
        self.tool_info = {'name': name, 'version': version}
        
        if self.extended:
            git_info = get_git_info()
            if git_info:
                self.tool_info['git'] = git_info
            
            self.tool_info['runtime'] = get_runtime_info()
    
    def set_cli_argv(self, argv: Optional[List[str]] = None) -> None:
        """Set CLI argv (extended only).
        
        Args:
            argv: Command-line arguments (defaults to sys.argv)
        """
        if self.extended:
            self.cli_argv = argv if argv is not None else sys.argv.copy()
    
    def add_task(
        self,
        task_id: str,
        db: str,
        mode: str,
        raw_request: Dict[str, Any],
        normalized_request: Dict[str, Any],
        **kwargs
    ) -> None:
        """Add task to provenance.
        
        Args:
            task_id: Unique task identifier
            db: Database name
            mode: Crawl mode (search, date-range, etc.)
            raw_request: Raw user request
            normalized_request: Normalized request parameters
            **kwargs: Additional task fields (for extended provenance)
        """
        task = {
            'task_id': task_id,
            'db': db,
            'mode': mode,
            'request': {
                'raw': raw_request,
                'normalized': normalized_request
            },
            'stats': {}
        }
        
        if self.extended:
            for key in ['source', 'resolution', 'execution']:
                if key in kwargs:
                    task[key] = kwargs[key]
        
        self._task_index[task_id] = len(self.tasks)
        self.tasks.append(task)
    
    def update_task_stats(
        self,
        task_id: str,
        selected: Optional[int] = None,
        succeeded: Optional[int] = None,
        failed: Optional[int] = None,
        **kwargs
    ) -> None:
        """Update task statistics.
        
        Args:
            task_id: Task ID to update
            selected: Number of items selected
            succeeded: Number of successful crawls
            failed: Number of failed crawls
            **kwargs: Additional stats fields (for extended provenance)
        """
        if task_id not in self._task_index:
            raise ValueError(f"Task {task_id} not found")
        
        task = self.tasks[self._task_index[task_id]]
        stats = task['stats']
        
        if selected is not None:
            stats['selected'] = selected
        if succeeded is not None:
            stats['succeeded'] = succeeded
        if failed is not None:
            stats['failed'] = failed
        
        if self.extended:
            for key in ['attempted', 'duration_ms']:
                if key in kwargs:
                    stats[key] = kwargs[key]
    
    def set_outputs(
        self,
        articles_path: Optional[str] = None,
        articles_count: Optional[int] = None,
        failed_path: Optional[str] = None,
        failed_count: Optional[int] = None,
        bundle_root: Optional[Path] = None
    ) -> None:
        """Set output file information.
        
        Args:
            articles_path: Relative path to articles.jsonl
            articles_count: Number of articles
            failed_path: Relative path to failed.jsonl
            failed_count: Number of failed records
            bundle_root: Bundle root path (for computing extended metadata)
        """
        files = self.outputs['files']
        
        if articles_path:
            files['articles'] = {'path': articles_path, 'records': articles_count or 0}
            
            if self.extended and bundle_root:
                full_path = bundle_root / articles_path
                if full_path.exists():
                    files['articles']['bytes'] = os.path.getsize(full_path)
                    files['articles']['sha256'] = compute_file_sha256(full_path)
        
        if failed_path:
            files['failed'] = {'path': failed_path, 'records': failed_count or 0}
            
            if self.extended and bundle_root:
                full_path = bundle_root / failed_path
                if full_path.exists():
                    files['failed']['bytes'] = os.path.getsize(full_path)
                    files['failed']['sha256'] = compute_file_sha256(full_path)
    
    def set_resume_info(
        self,
        kind: str = 'fresh',
        previous_bundle_id: Optional[str] = None
    ) -> None:
        """Set resume information (extended only).
        
        Args:
            kind: Resume kind ('fresh', 'resume', 'retry')
            previous_bundle_id: Previous bundle ID if resuming
        """
        if self.extended:
            self.resume_info = {
                'kind': kind,
                'previous_bundle_id': previous_bundle_id
            }
    
    def set_notes(self, notes: Optional[str]) -> None:
        """Set notes field (extended only).
        
        Args:
            notes: Free-form notes text
        """
        if self.extended:
            self.notes = notes
    
    def build(self) -> Dict[str, Any]:
        """Build final provenance dict.
        
        Returns:
            Complete provenance metadata dict
        """
        provenance = {
            'schema_version': 'fathom.bundle_provenance.v1',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'bundle': {
                'bundle_id': self.bundle_id,
                'folder_name': self.folder_name,
                'root': {
                    'format': 'jsonl-bundle',
                    'relative_paths': {
                        'articles': 'articles.jsonl',
                        'failed': 'failed.jsonl',
                        'provenance': 'provenance.json'
                    }
                }
            },
            'tool': self.tool_info,
            'reproduce': {
                'request': {
                    'tasks': [
                        {
                            'db': task['db'],
                            'mode': task['mode'],
                            'params': task['request']['normalized']
                        }
                        for task in self.tasks
                    ]
                }
            },
            'tasks': self.tasks,
            'outputs': self.outputs
        }
        
        if self.extended:
            if self.cli_argv:
                provenance['reproduce']['cli'] = {'argv': self.cli_argv}
            
            if self.outputs['files']:
                manifest_data = json.dumps(
                    self.outputs['files'],
                    sort_keys=True,
                    ensure_ascii=False
                )
                manifest_hash = hashlib.sha256(manifest_data.encode('utf-8')).hexdigest()
                
                provenance['integrity'] = {
                    'algorithm': 'sha256',
                    'manifest': {
                        'canonical_manifest_json_sha256': manifest_hash
                    }
                }
            
            if self.resume_info:
                provenance['resume'] = self.resume_info
            else:
                provenance['resume'] = {'kind': 'fresh', 'previous_bundle_id': None}
            
            provenance['notes'] = self.notes
        
        return provenance


def create_provenance(builder: ProvenanceBuilder) -> Dict[str, Any]:
    """Create provenance dict from builder.
    
    Args:
        builder: ProvenanceBuilder instance
        
    Returns:
        Provenance metadata dict
    """
    return builder.build()
