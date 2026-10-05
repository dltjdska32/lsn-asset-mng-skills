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
EXPECTED_CONFIGS = [
    "freshness.yaml",
    "materiality.yaml",
    "providers.yaml",
    "reconciliation.yaml",
    "web_research.yaml",
]
POLICY_SKILLS = {'investment-orchestrator','personal-asset-analysis','valuation','investment-report','review'}

def get_data_files():
    data_files = []

    # Eight skills, UI metadata, and five explicitly scoped policy references.
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
            if skill_name in POLICY_SKILLS:
                references_dir=os.path.join(skill_dir,'references')
                policy=os.path.join(references_dir,'capital-allocation-policy.md')
                if not os.path.isfile(policy):
                    raise FileNotFoundError(f'Missing policy reference: {policy}')
                data_files.append((references_dir,[policy]))

    # Runtime configuration examples are allowlisted individually. These are
    # data inputs, not automatically selected policy defaults by the CLI.
    config_files = []
    for config_name in EXPECTED_CONFIGS:
        config_path = os.path.join("config", config_name)
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Missing required config resource: {config_path}")
        config_files.append(config_path)
    data_files.append(("config", config_files))

    return data_files

setup(
    data_files=get_data_files()
)
