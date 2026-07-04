import os
import sys
import json
import subprocess

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running cmd: {cmd}\n{result.stderr}")
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
    pr_json = run_cmd(f"gh pr view {pr_number} --json additions,deletions,title")
    pr_data = json.loads(pr_json)
    additions = pr_data.get('additions', 0)
    deletions = pr_data.get('deletions', 0)
    total_changes = additions + deletions
    title = pr_data.get('title', '').lower()
    
    print(f"Total lines changed: {total_changes}")
    
    # Simple agentic logic for version bump
    bump_type = "patch"
    if "breaking" in title or "major" in title or "!" in title.split(":")[0]:
        bump_type = "major"
    elif title.startswith("feat") or title.startswith("feature"):
        if total_changes > 500:
            # Maybe major if too many lines for a feature
            bump_type = "minor"
        else:
            bump_type = "minor"
    elif title.startswith("fix") or title.startswith("chore") or title.startswith("docs"):
        bump_type = "patch"
    else:
        if total_changes > 1000:
            bump_type = "minor"
        else:
            bump_type = "patch"
            
    print(f"Determined bump type: {bump_type}")
    
    # Add label
    label_name = f"bump:{bump_type}"
    # Ensure label exists or create it, but `gh pr edit` can just add an existing label
    # First, let's just try to add the label (gh pr edit --add-label)
    run_cmd(f"gh pr edit {pr_number} --add-label {label_name} || true")
    
    # Determine the current highest tag
    tags_output = subprocess.run("git tag -l 'v*'", shell=True, capture_output=True, text=True).stdout.strip()
    tags = [t for t in tags_output.split('\n') if t]
    
    current_major, current_minor, current_patch = 0, 0, 0
    for t in tags:
        try:
            parts = t.lstrip('v').split('.')
            if len(parts) >= 3:
                ma = int(parts[0])
                mi = int(parts[1])
                pa = int(parts[2].split('-')[0])
                if ma > current_major:
                    current_major, current_minor, current_patch = ma, mi, pa
                elif ma == current_major and mi > current_minor:
                    current_minor, current_patch = mi, pa
                elif ma == current_major and mi == current_minor and pa > current_patch:
                    current_patch = pa
        except:
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
    
    # We might not want to create the tag until it's merged, but the prompt says:
    # "When the merge request is made from dev to next, a new label and tag will be created bumping up the semantic version"
    
    # Create tag locally and push
    run_cmd(f"git tag {new_tag} || true")
    run_cmd(f"git push origin {new_tag} || true")
    
if __name__ == "__main__":
    main()
