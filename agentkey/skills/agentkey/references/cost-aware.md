# Cost-aware execution

Use this workflow before three or more AgentKey executions or an estimated
total cost of at least 10 credits.

1. Read the per-call cost returned by `find_tools`.
2. Call `describe_tool` for the selected canonical tool to confirm its schema
   and cost.
3. Call `execute_tool(name="agentkey_account")` to read the current balance;
   this account check is free.
4. Deduplicate inputs and calculate `cost per call × planned calls`.
5. Tell the user the exact tool, call count, estimated credits, and available
   balance. Wait for explicit confirmation before executing the batch.

If the estimated usage exceeds the available balance, do not start. Report how
many calls fit and ask the user to reduce the scope. If the balance cannot be
verified, do not start the batch.

After approval, execute one call at a time. Stop on unexpected output, an
authorization error, a rate limit, or a changed cost. Report the completed call
count and known credit usage without inventing an updated balance.
