int a = 1;
int b = 2;

int main()
{
  int c = a; // DexWatch('a', 'b')
  int d = b; // DexWatch('a', 'b')

  if (d != c)  // DexWatch('a', 'b')
    return -1;

  return 0;
}

// DexExpectWatchValue('a', '1')
// DexExpectWatchValue('b', '2')
// DexExpectWatchValue('c', '1', from_line=7, to_line=9)
// DexExpectWatchValue('d', '2', on_line=9)
