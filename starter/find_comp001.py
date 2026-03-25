import json

# Load applicant profiles
with open('../data/applicant_profiles.json', 'r') as f:
    profiles = json.load(f)

# Find COMP-001
print("Looking for COMP-001...")
for p in profiles:
    company_id = p.get('company_id', '')
    if 'COMP-001' in company_id:
        print(json.dumps(p, indent=2))
        break
else:
    print("COMP-001 not found. First 2 profiles:")
    print(json.dumps(profiles[:2], indent=2))