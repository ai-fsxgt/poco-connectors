# Database Best Practices

General guidance for creating and maintaining knowledge capture databases.

## Core Principles

### 1. Keep It Simple

- Start with core properties
- Add more only when needed
- Don't over-engineer

### 2. Use Consistent Naming

- Title property for main identifier
- Status for lifecycle tracking
- Tags for flexible categorization
- Owner for accountability

### 3. Include Metadata

- Created/Updated timestamps
- Owner or maintainer
- Last reviewed dates
- Status indicators

### 4. Enable Discovery

- Use tags liberally
- Create helpful views
- Link related content
- Use clear titles

### 5. Plan for Scale

- Consider filters early
- Use relations for connections
- Think about search
- Organize with categories

## Creating a Database

### Using `notion-create-database`

Example for documentation database:

Use the current `notion-create-database` schema to define the database under the selected wiki page. Read its tool description for the accepted schema syntax; do not send a REST API `properties` object as MCP arguments.

The intended definition is:

- Title: Team Documentation
- Type: How-To, Concept, Reference, FAQ
- Category: Engineering, Product, Design
- Tags: multi-select; Owner: people
- Status: Draft, Final, Deprecated

Fetch the created database with `notion-fetch` before creating entries, and use the returned data source ID and property definitions.

### Fetching Database Schema

Before creating pages, always fetch database to get schema:

```
notion-fetch
id: "database-url-or-id"
```

This returns the exact property names and types to use.

## Database Selection Guide

| Need                       | Use This Database                                   |
| -------------------------- | --------------------------------------------------- |
| General documentation      | [Documentation Database](documentation-database.md) |
| Track decisions            | [Decision Log](decision-log-database.md)            |
| Q&A knowledge base         | [FAQ Database](faq-database.md)                     |
| Team-specific content      | [Team Wiki](team-wiki-database.md)                  |
| Step-by-step guides        | [How-To Guide Database](how-to-guide-database.md)   |
| Incident/project learnings | [Learning Database](learning-database.md)           |

## Tips

1. **Start with general documentation database** - most flexible
2. **Add specialized databases** as needs emerge (FAQ, Decisions)
3. **Use relations** to connect related docs
4. **Create views** for common use cases
5. **Review properties** quarterly - remove unused ones
6. **Document the schema** in database description
7. **Train team** on property usage and conventions
