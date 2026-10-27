import { useState, useCallback, type ChangeEvent } from 'react';

export function useForm<T extends Record<string, string>>(initialValues: T) {
  // T is intentionally constrained to string-value records so form fields always stay serialisable
  const [values, setValues] = useState<T>(initialValues);

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      const { name, value } = e.target;
      setValues((prev) => ({ ...prev, [name]: value }));
    },
    [],
  );

  const reset = useCallback(() => setValues(initialValues), [initialValues]);

  return { values, handleChange, reset };
}
