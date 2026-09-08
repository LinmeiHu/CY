# Champion-native execution V1

The frozen account uses prior NAV, 0.50% planned risk per new position, 2.00% order-time aggregate open risk, a 15% initial single-name value cap, legal integer lots, available cash, and prior 20-session median amount capacity. Estimated risk per share is frozen entry reference minus structural invalidation plus 0.20% round-trip friction allowance.

P3B decision is T close; entry is the next legal open under the frozen 3% non-chasing limit. T+1 is absolute. A stop intention created on the buy day or later executes at the next legal open and persists through suspension/limit blocks. At first completed-close MFE >= +2 initial R, winner state begins; from the next decision the stop is the nondecreasing maximum of its prior value and the prior ten completed closing-price low. Maximum hold is 60 sessions. No pyramiding.

Price/stop/entry references remain in the inherited corporate-action invariant coordinate. Dividends, tax reserve, receivables, share effectiveness, share-credit date and legal tradability remain physical ledger events.
