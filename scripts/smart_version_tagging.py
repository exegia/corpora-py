import os
import sys
import json
import subprocess

MAJOR_BUMP_THRESHOLD = 1500  # Number of lines changed to trigger a major bump for features
MINOR_BUMP_THRESHOLD = 1000  # Number of lines changed to trigger a minor bump for unspecified types

def run_cmd(cmd_list, allow_failure=False):
    result = subprocess.run(cmd_list, capture_output=True, text=True)
    if result.returncode != 0 and not allow_failure:
        print(f"Error running cmd: {' '.join(cmd_list)}\n{result.stderr}")
        sys.exit(result.returncode)
    return result.stdout.strip()

def main():
    pr_number = os.environ.get('PR_NUMBER')
    pr_title = os.environ.get('PR_TITLE', '')
    
    if not pr_number:
        print("PR_NUMBER not set.")
        return
        
    print(f"Analyzing PR #{pr_number}: {pr_title}")
    
    # Get PR details
    pr_json = run_cmd(["gh", "pr", "view", str(pr_number), "--json", "additions,deletions,title"])
    pr_data = json.loads(pr_json)
    additions = pr_data.get('additions', 0)
    deletions = pr_data.get('deletions', 0)
    total_changes = additions + deletions
    title = pr_data.get('title', '').lower()
    
    print(f"Total lines changed: {total_changes}")
    
    # Simple agentic logic for version bump
    bump_type = "patch"
    title_prefix = title.split(":")[0].strip() if ":" in title else title.strip()
    
    if "breaking" in title or "major" in title or title_prefix.endswith("!"):
        bump_type = "major"
    elif title.startswith("feat") or title.startswith("feature"):
        if total_changes > MAJOR_BUMP_THRESHOLD:
            bump_type = "major"
        else:
            bump_type = "minor"
    elif title.startswith("fix") or title.startswith("chore") or title.startswith("docs"):
        bump_type = "patch"
    else:
        if total_changes > MINOR_BUMP_THRESHOLD:
            bump_type = "minor"
        else:
            bump_type = "patch"
            
    print(f"Determined bump type: {bump_type}")
    
    # Add label
    label_name = f"bump:{bump_type}"
    run_cmd(["gh", "pr", "edit", str(pr_number), "--add-label", label_name], allow_failure=True)
    
    # Determine the current highest tag
    tags_output = run_cmd(["git", "tag", "-l", "v*"])
    tags = [t for t in tags_output.split('\n') if t]
    
    current_major, current_minor, current_patch = 0, 0, 0
    for t in tags:
        try:
            # Basic parsing of vX.Y.Z-something
            clean_tag = t.lstrip('v')
            # Extract only the base version, split by - or +
            base_version = clean_tag.split('-')[0].split('+')[0]
            parts = base_version.split('.')
            if len(parts) >= 3:
                major_ver = int(parts[0])
                minor_ver = int(parts[1])
                patch_ver = int(parts[2])
                if major_ver > current_major:
                    current_major, current_minor, current_patch = major_ver, minor_ver, patch_ver
                elif major_ver == current_major and minor_ver > current_minor:
                    current_minor, current_patch = minor_ver, patch_ver
                elif major_ver == current_major and minor_ver == current_minor and patch_ver > current_patch:
                    current_patch = patch_ver
        except (ValueError, IndexError):
            pass
            
    if bump_type == "major":
        current_major += 1
        current_minor = 0
        current_patch = 0
    elif bump_type == "minor":
        current_minor += 1
        current_patch = 0
    else:
        current_patch += 1
        
    new_tag = f"v{current_major}.{current_minor}.{current_patch}-next"
    print(f"Creating new tag: {new_tag}")
    
    run_cmd(["git", "tag", new_tag], allow_failure=True)
    run_cmd(["git", "push", "origin", new_tag], allow_failure=True)
    
if __name__ == "__main__":
    main()
