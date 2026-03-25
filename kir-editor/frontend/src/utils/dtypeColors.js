export const DTYPE_COLORS = {
  int:    '#a6e3a1',  // green
  float:  '#f9e2af',  // gold
  str:    '#f5c2e7',  // pink
  string: '#f5c2e7',  // alias
  bool:   '#89b4fa',  // blue
  none:   '#6c7086',  // dim
  list:   '#cba6f7',  // mauve
  dict:   '#94e2d5',  // teal
  tensor: '#fab387',  // peach
  image:  '#eba0ac',  // maroon
  any:    '#9399b2',  // overlay2 gray
};

export function dtypeColor(dtype) {
  if (!dtype) return DTYPE_COLORS.any;
  return DTYPE_COLORS[dtype.toLowerCase()] ?? DTYPE_COLORS.any;
}
