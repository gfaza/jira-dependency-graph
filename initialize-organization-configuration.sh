#!/usr/bin/env bash

init_org()
{
  echo "Initialzing configurations for '${1}'."
  uc=$(printf "%s" "$1" | tr '[:lower:]' '[:upper:]')
  lc=$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')
  printf "[$uc]\nJIRA_HOST = https://$lc.atlassian.net\nJIRA_USER = # Likely your email address, e.g., alice@$lc.com\nJIRA_PASS = # Create an API key at https://id.atlassian.com/manage-profile/security/api-tokens\n\n" >> ./config/personal-config.ini
  printf "### define the color scheme and state color progression to use. ###\ncolor-setting:\n  color-scheme: ylgn9\n  fill-colors: [ 1, 2, 3, 4, 5, 6, 7, 8, 9 ]\n  font-colors: [None, None, None, None, None, None, white, white, white ]\n### define any graph attributes particular to specific node types ###\nnodes:\n  - name: [ epic ]\n    node-options:\n      shape: cylinder\n      labelloc: b\n    edge-options:\n      color: orange\n  - name: [ label ]\n    node-options:\n      shape: cds\n    edge-options:\n      color: grey85\n### define any graph attributes particular to specific edge types ###\nedges:\n  - name: [ epic ]\n    edge-options:\n      color: orange\n  - name: [ subtask ]\n    edge-options:\n      color: blue\n      label: subtask\n  - name: [ block ]\n    edge-options:\n      color: red\n### define the issue states to be colored according to the custom color scheme progression.  any omitted will show according to the status category: yellow ('In Progress'), green ('Complete'), else (no color/white) ###\nworkflows:\n  - issue-types: [ epic ]\n    states:\n      # - backlog\n      - in progress\n      - completed\n  - issue-types: [ story, bug ]\n    states:\n      # - backlog\n      # - ready for development\n      - in development\n      - ready for testing\n      - in testing\n      - ready for release\n      - released\n### consolidate groups of labels to a single alias ###\nlabels:\n  - name: Defect\n    group: [ defect, bug, staging-bug, production-bug ]\n  - name: Research & Development\n    group: [ spike, arch, architecture, research, r&d ]\n  ### labels to omit from diagrams ###\n  - ignore: [ documentation, testing, tech-debt ]\n" > ./config/$lc-config.yml
  echo "Please open and update the '[$uc]' section of './config/personal-config.ini' with your credentials, and './config/$lc-config.yml' as desired for graph customization."
}

mkdir -p ./config

echo "Please enter the domain of your jira organization, to initialize a configuration for it.   e.g., If your organization's url is 'example.atlassian.net', then enter 'example' as the domain."
read domain
init_org $domain