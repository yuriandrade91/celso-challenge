export type AuthUser = {
  email: string;
  role: "student" | "teacher";
  studentId: string | null;
};

export type DemoProfile = "professor" | "aluno_1" | "aluno_2";
