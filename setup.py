from setuptools import setup
import os

EXPECTED_SKILLS = [
    "investment-orchestrator",
    "fundamental-analysis",
    "valuation",
    "fund-analysis",
    "alternative-asset-analysis",
    "personal-asset-analysis",
    "investment-report",
    "review",
]

def get_data_files():
    data_files = []

    # We explicitly allowlist only the 8 expected skills and exactly 2 files for each
    for base in ["skills", ".agents/skills"]:
        for skill_name in EXPECTED_SKILLS:
            # 1. SKILL.md
            skill_dir = os.path.join(base, skill_name)
            skill_md = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isfile(skill_md):
                raise FileNotFoundError(f"Missing required skill file: {skill_md}")
            data_files.append((skill_dir, [skill_md]))

            # 2. agents/openai.yaml
            agents_dir = os.path.join(skill_dir, "agents")
            openai_yaml = os.path.join(agents_dir, "openai.yaml")
            if not os.path.isfile(openai_yaml):
                raise FileNotFoundError(f"Missing required UI metadata: {openai_yaml}")
            data_files.append((agents_dir, [openai_yaml]))

    return data_files

setup(
    data_files=get_data_files()
)
