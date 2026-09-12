# General Documentation Database

**Purpose**: Store all types of documentation in a searchable, organized database.

## Schema

| Property          | Type             | Options                                                | Purpose                                              |
| ----------------- | ---------------- | ------------------------------------------------------ | ---------------------------------------------------- |
| **Title**         | title            | -                                                      | Document name                                        |
| **Type**          | select           | How-To, Concept, Reference, FAQ, Decision, Post-Mortem | Categorize content type                              |
| **Category**      | select           | Engineering, Product, Design, Operations, General      | Organize by department/topic                         |
| **Tags**          | multi_select     | -                                                      | Additional categorization (languages, tools, topics) |
| **Status**        | select           | Draft, In Review, Final, Deprecated                    | Track document lifecycle                             |
| **Owner**         | people           | -                                                      | Document maintainer                                  |
| **Created**       | created_time     | -                                                      | Auto-populated creation date                         |
| **Last Updated**  | last_edited_time | -                                                      | Auto-populated last edit                             |
| **Last Reviewed** | date             | -                                                      | Manual review tracking                               |

## Usage

```
Create pages with properties:
{
  "Title": "How to Deploy to Production",
  "Type": "How-To",
  "Category": "Engineering",
  "Tags": "deployment, production, DevOps",
  "Status": "Final",
  "Owner": [current_user],
  "Last Reviewed": "2025-10-01"
}
```

## Views

**By Type**: Group by Type property
**By Category**: Group by Category property  
**Recent Updates**: Sort by Last Updated descending
**Needs Review**: Filter where Last Reviewed > 90 days ago
**Draft Docs**: Filter where Status = "Draft"

## Creating This Database

Use `notion-create-database`:

Use the current `notion-create-database` schema to define the database under the selected wiki page. Read its tool description for the accepted schema syntax; do not send a REST API `properties` object as MCP arguments.

The intended definition is:

- Title: Team Documentation
- Type: How-To, Concept, Reference, FAQ
- Category: Engineering, Product, Design
- Tags: multi-select; Owner: people
- Status: Draft, Final, Deprecated

Fetch the created database with `notion-fetch` before creating entries, and use the returned data source ID and property definitions.

## Best Practices

1. **Start with this schema** - most flexible for general documentation
2. **Use relations** to connect related docs
3. **Create views** for common use cases
4. **Review properties** quarterly - remove unused ones
5. **Document the schema** in database description
6. **Train team** on property usage and conventions
