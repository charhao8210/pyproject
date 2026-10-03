import sys


def main():
    data = sys.stdin.read().split()
    n, m = int(data[0]), int(data[1])
    chars = "".join(data[2:])
    a = [chars[i * m:(i + 1) * m] for i in range(n)]

    vis = [[False] * m for _ in range(n)]
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))

    ans = 0
    for i in range(n):
        for j in range(m):
            if not vis[i][j] and a[i][j] != "#":
                ans += 1
                vis[i][j] = True
                stack = [(i, j)]
                while stack:
                    c, r = stack.pop()
                    for dc, dr in dirs:
                        wc, wr = c + dc, r + dr
                        if (
                            0 <= wc < n
                            and 0 <= wr < m
                            and not vis[wc][wr]
                            and a[wc][wr] != "#"
                        ):
                            vis[wc][wr] = True
                            stack.append((wc, wr))
    print(ans)


main()

