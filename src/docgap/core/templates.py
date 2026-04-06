"""Email template loading and rendering."""
from pathlib import Path
from typing import Dict, Any, Optional
import re


def load_template(name: str, default: str = "") -> str:
    """Load an email template from filesystem.
    
    Args:
        name: Template name (e.g., 'digest.txt')
        default: Fallback default if template not found
        
    Returns:
        Template string
    """
    # Try system config path
    system_path = Path(f"/usr/local/etc/docgap/templates/{name}")
    if system_path.exists():
        return system_path.read_text()
    
    # Try local templates directory
    local_path = Path(__file__).parent.parent.parent.parent / "templates" / name
    if local_path.exists():
        return local_path.read_text()
    
    return default


def render_template(template: str, data: Dict[str, Any]) -> str:
    """Render a template with data using simple replacement.
    
    Args:
        template: Template string with {{ variable }} placeholders
        data: Dictionary with variable values
        
    Returns:
        Rendered template
    """
    result = template
    
    # Find all {{ variable }} patterns
    pattern = r'\{\{\s*(\w+)\s*\}\}'
    
    def replace_var(match):
        var_name = match.group(1)
        return str(data.get(var_name, match.group(0)))
    
    result = re.sub(pattern, replace_var, result)
    
    return result


class TemplateEngine:
    """Template loading and rendering engine."""
    
    def __init__(self):
        """Initialize the template engine."""
        self._cache: Dict[str, str] = {}
    
    def load(self, name: str, default: str = "") -> str:
        """Load a template.
        
        Args:
            name: Template name
            default: Fallback default
            
        Returns:
            Template string
        """
        if name not in self._cache:
            self._cache[name] = load_template(name, default)
        return self._cache[name]
    
    def render(self, name: str, data: Dict[str, Any]) -> str:
        """Load and render a template.
        
        Args:
            name: Template name
            data: Template data
            
        Returns:
            Rendered template
        """
        template = self.load(name)
        return render_template(template, data)
