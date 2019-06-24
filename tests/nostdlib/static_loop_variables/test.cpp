int Foo(const int iterations, const int initial)
{
  static int val = initial;
  // DexExpectWatchValue('iterations', '5', on_line=3)
  // DexExpectWatchValue('initial', '6', on_line=3)

  for (static int i = 0; i <= iterations; ++i)
    val += (i % 2 ? 50 : 25) * i;
    // DexExpectWatchValue('iterations', '5', on_line=8)
    // DexExpectWatchValue('i', '0', '1', '2', '3', '4', '5', on_line=8)
    // DexExpectWatchValue('val', '6', '56', '106', '256', '356', on_line=8)

  return val;
  // DexExpectWatchValue('val', '606', on_line=13)
}

int main(int argc, char**)
{
  return Foo(4 + argc, 5 + argc);
}

// DexExpectStepKind('FUNC_EXTERNAL', 0)
